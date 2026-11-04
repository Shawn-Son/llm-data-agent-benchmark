"""DocETL operators on lists of documents (dicts)."""
from __future__ import annotations
import json, re
from collections import defaultdict
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

from ..llm import BaseLLM

Doc = Dict[str, Any]


def render(template: str, **ctx) -> str:
    """Minimal Jinja-like rendering: {{ input.key }}, {{ input }}, {{ inputs }}, {{ reduce_key }}."""
    def sub(m):
        expr = m.group(1).strip()
        obj = ctx
        for part in expr.split('.'):
            if isinstance(obj, dict) and part in obj: obj = obj[part]
            else: return ''
        return obj if isinstance(obj, str) else json.dumps(obj, ensure_ascii=False, default=str)
    return re.sub(r'\{\{\s*(.*?)\s*\}\}', sub, template)


def _schema_text(schema: Dict[str, str]) -> str:
    return json.dumps(schema, ensure_ascii=False)


def _validate(doc: Doc, out: Dict[str, Any], validations: Sequence[Callable[[Doc, Dict[str, Any]], bool]]) -> Optional[str]:
    for i, v in enumerate(validations):
        try:
            if not v(doc, out): return f'validation {i} failed: {getattr(v, "__doc__", None) or v.__name__}'
        except Exception as e: return f'validation {i} raised {e!r}'
    return None


def map_op(llm: BaseLLM, docs: Sequence[Doc], prompt: str, schema: Dict[str, str], *, validations: Sequence[Callable] = (),
           retries: int = 2, model: Optional[str] = None, drop_keys: Sequence[str] = (), tag: str = 'map') -> List[Doc]:
    """LLM projection per document; output keys are added to the document (Sec. 2.2.1).
    Validations are Python predicates (doc, output) -> bool; a failure retries with the
    failure context (Sec. 2.1 fault tolerance)."""
    out_docs = []
    for doc in docs:
        user = render(prompt, input=doc) + '\n\nReply with a JSON object with exactly this schema: ' + _schema_text(schema)
        feedback = ''
        result: Dict[str, Any] = {}
        for attempt in range(retries + 1):
            res = llm.json(user + feedback, model=model, max_tokens=2000, tag=f'extract.{tag}')
            result = res if isinstance(res, dict) else {'value': res}
            err = _validate(doc, result, validations)
            if err is None: break
            feedback = f'\n\nYour previous answer {json.dumps(result)[:500]} failed: {err}. Fix it.'
        new = {k: v for k, v in doc.items() if k not in drop_keys}
        new.update({k: result.get(k) for k in schema})
        out_docs.append(new)
    return out_docs


def parallel_map(llm: BaseLLM, docs: Sequence[Doc], prompts: Sequence[Tuple[str, Dict[str, str]]], **kw) -> List[Doc]:
    """Independent projections merged into each document (Sec. 2.2.1); used by the isolating rewrite."""
    cur = list(docs)
    for i, (prompt, schema) in enumerate(prompts):
        cur = map_op(llm, cur, prompt, schema, tag=f'pmap{i}', **kw)
    return cur


def filter_op(llm: BaseLLM, docs: Sequence[Doc], prompt: str, **kw) -> List[Doc]:
    res = map_op(llm, docs, prompt, {'keep': 'boolean'}, tag='filter', **kw)
    return [{k: v for k, v in d.items() if k != 'keep'} for d in res if d.get('keep')]


def unnest(docs: Sequence[Doc], key: str, keep_parent_keys: bool = True) -> List[Doc]:
    out = []
    for d in docs:
        items = d.get(key)
        if isinstance(items, dict):
            new = dict(d) if keep_parent_keys else {}; new.pop(key, None); new.update(items); out.append(new)
        elif isinstance(items, list):
            for it in items:
                new = dict(d) if keep_parent_keys else {}; new.pop(key, None)
                if isinstance(it, dict): new.update(it)
                else: new[key] = it
                out.append(new)
        else: out.append(dict(d))
    return out


def split(docs: Sequence[Doc], key: str, chunk_chars: int = 4000, overlap: int = 0) -> List[Doc]:
    """Split a long text field into chunks with ids for later reassembly (Sec. 2.3.2)."""
    out = []
    for di, d in enumerate(docs):
        text = str(d.get(key) or '')
        if not text: out.append({**d, f'{key}_chunk': '', 'chunk_id': f'{di}-0', 'chunk_num': 0, 'doc_index': di}); continue
        start, n = 0, 0
        while start < len(text):
            end = min(len(text), start + chunk_chars)
            if end < len(text):
                cut = text.rfind('\n', start, end)
                if cut > start + chunk_chars // 2: end = cut
            out.append({**d, f'{key}_chunk': text[start:end], 'chunk_id': f'{di}-{n}', 'chunk_num': n, 'doc_index': di})
            n += 1; start = max(end - overlap, start + 1)
    return out


def gather(chunks: Sequence[Doc], key: str, previous: int = 1, following: int = 0, summary_key: Optional[str] = None) -> List[Doc]:
    """Add peripheral context from neighbouring chunks of the same document (Sec. 2.3.3)."""
    by_doc: Dict[int, List[Doc]] = defaultdict(list)
    for c in chunks: by_doc[c['doc_index']].append(c)
    out = []
    for c in chunks:
        sibs = sorted(by_doc[c['doc_index']], key=lambda x: x['chunk_num'])
        i = c['chunk_num']
        before = sibs[max(0, i - previous):i]; after = sibs[i + 1:i + 1 + following]
        parts = []
        for b in before: parts.append('<context_before>' + (b.get(summary_key) if summary_key else b[f'{key}_chunk']) + '</context_before>')
        parts.append('<chunk>' + c[f'{key}_chunk'] + '</chunk>')
        for a in after: parts.append('<context_after>' + (a.get(summary_key) if summary_key else a[f'{key}_chunk']) + '</context_after>')
        out.append({**c, f'{key}_rendered': '\n'.join(parts)})
    return out


def reduce_op(llm: BaseLLM, docs: Sequence[Doc], keys: Sequence[str], prompt: str, schema: Dict[str, str], *,
              fold_prompt: Optional[str] = None, fold_batch: int = 20, model: Optional[str] = None,
              scratchpad: bool = True) -> List[Doc]:
    """Group-by + LLM aggregation with batched folding and a scratchpad (Sec. 2.2.2, Fig. 2).
    One output document per distinct key combination."""
    groups: Dict[Tuple, List[Doc]] = defaultdict(list)
    for d in docs: groups[tuple(d.get(k) for k in keys)].append(d)
    out = []
    for kv, items in groups.items():
        reduce_key = dict(zip(keys, kv))
        acc: Optional[Dict[str, Any]] = None; pad = ''
        for b in range(0, len(items), fold_batch):
            batch = items[b:b + fold_batch]
            if acc is None:
                user = render(prompt, inputs=batch, reduce_key=reduce_key)
            else:
                fp = fold_prompt or (prompt + '\n\nYou already produced this accumulated output from earlier documents:\n{{ accumulated }}\n'
                                     'Update it with the new documents below so that it reflects all documents seen so far.')
                user = render(fp, inputs=batch, reduce_key=reduce_key, accumulated=acc)
            if scratchpad:
                user += ('\n\nYou may keep private notes (counts, partial lists) in a "scratchpad" string field; '
                         'the current scratchpad is: ' + json.dumps(pad))
            user += '\n\nReply with a JSON object with this schema: ' + _schema_text({**schema, **({'scratchpad': 'string'} if scratchpad else {})})
            res = llm.json(user, model=model, max_tokens=3000, tag='extract.reduce')
            if not isinstance(res, dict): res = {'value': res}
            pad = str(res.pop('scratchpad', pad)) if scratchpad else ''
            acc = res
        out.append({**reduce_key, **{k: (acc or {}).get(k) for k in schema}, '_count': len(items)})
    return out


def _norm(s: Any) -> str:
    return re.sub(r'[^0-9a-z]+', ' ', str(s or '').lower()).strip()


def _sim(a: str, b: str) -> float:
    ta, tb = set(a.split()), set(b.split())
    if not ta or not tb: return 0.0
    j = len(ta & tb) / len(ta | tb)
    if a.replace(' ', '') == b.replace(' ', ''): return 1.0
    return max(j, 1.0 if (a in b or b in a) else 0.0)


def resolve(llm: Optional[BaseLLM], docs: Sequence[Doc], key: str, *, comparison_prompt: Optional[str] = None,
            resolution_prompt: Optional[str] = None, blocking_threshold: float = 0.4, model: Optional[str] = None,
            canonical_fn: Optional[Callable[[List[str]], str]] = None, context_keys: Sequence[str] = ()) -> List[Doc]:
    """Canonicalise variations of `key` across documents (Sec. 2.2.3, directive 9).

    Blocking: pairs of distinct values whose token similarity >= blocking_threshold (or
    whose space-less forms are equal) are compared; with an LLM the comparison prompt decides,
    without one the blocking rule is the decision. Groups are unioned, then a canonical value
    is chosen by the resolution prompt (or canonical_fn, default: most frequent value).
    """
    values = [str(d.get(key)) for d in docs if d.get(key) not in (None, '')]
    distinct = sorted(set(values), key=lambda v: (-values.count(v), v))
    norm = {v: _norm(v) for v in distinct}
    parent = {v: v for v in distinct}

    def find(x):
        while parent[x] != x: parent[x] = parent[parent[x]]; x = parent[x]
        return x
    for i, a in enumerate(distinct):
        for b in distinct[i + 1:]:
            if find(a) == find(b): continue
            s = _sim(norm[a], norm[b])
            if s < blocking_threshold: continue
            same = True
            if llm is not None and s < 1.0:
                da = next(d for d in docs if str(d.get(key)) == a); db = next(d for d in docs if str(d.get(key)) == b)
                cp = comparison_prompt or ('Do the following two values of "' + key + '" refer to the same entity?\n'
                                           'Value 1: {{ input1.' + key + ' }}\nValue 2: {{ input2.' + key + ' }}')
                user = render(cp, input1=da, input2=db)
                if context_keys: user += '\nContext 1: ' + json.dumps({k: da.get(k) for k in context_keys}, default=str)[:800] + \
                                         '\nContext 2: ' + json.dumps({k: db.get(k) for k in context_keys}, default=str)[:800]
                res = llm.json(user + '\n\nReply with JSON: {"same": true|false}', model=model, max_tokens=100, tag='extract.resolve.compare')
                same = bool(res.get('same')) if isinstance(res, dict) else False
            if same: parent[find(b)] = find(a)
    groups: Dict[str, List[str]] = defaultdict(list)
    for v in distinct: groups[find(v)].append(v)
    canon: Dict[str, str] = {}
    for root, members in groups.items():
        if len(members) == 1: canon[members[0]] = members[0]; continue
        if canonical_fn is not None: c = canonical_fn(members)
        elif llm is not None:
            rp = resolution_prompt or ('The following values refer to the same entity:\n{{ inputs }}\n'
                                       'Provide one canonical value that best represents them.')
            res = llm.json(render(rp, inputs=members) + '\n\nReply with JSON: {"' + key + '": "..."}', model=model,
                           max_tokens=200, tag='extract.resolve.canonical')
            c = str(res.get(key)) if isinstance(res, dict) and res.get(key) else members[0]
        else: c = members[0]
        for m in members: canon[m] = c
    return [{**d, key: canon.get(str(d.get(key)), d.get(key)), f'{key}_original': d.get(key)} for d in docs]
