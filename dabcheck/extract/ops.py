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


_TYPES = {'string': str, 'str': str, 'text': str, 'integer': int, 'int': int, 'number': (int, float), 'float': (int, float),
          'boolean': bool, 'bool': bool, 'list': list, 'array': list, 'dict': dict, 'object': dict}


def validate_output_types(out: Any, schema: Dict[str, str]) -> Optional[str]:
    """DocETL validate_output_types: every schema key present with a compatible type. Schema values
    are free-text type names ('string', 'list[str]', 'integer or null', ...); unknown names pass."""
    if not isinstance(out, dict): return 'output is not a JSON object'
    for k, t in schema.items():
        if k not in out: return f'missing key {k!r}'
        v = out[k]
        if v is None: continue
        base = str(t).lower().split('[')[0].split(' ')[0].strip()
        py = _TYPES.get(base)
        if py is None: continue
        if py is int and isinstance(v, bool): return f'{k!r} should be {t}'
        if py in (int,) and isinstance(v, float) and v == int(v): continue
        if not isinstance(v, py): return f'{k!r} should be {t}, got {type(v).__name__}'
    return None


def _validate(doc: Doc, out: Dict[str, Any], validations: Sequence[Callable[[Doc, Dict[str, Any]], bool]]) -> Optional[str]:
    for i, v in enumerate(validations):
        try:
            if not v(doc, out): return f'validation {i} failed: {getattr(v, "__doc__", None) or v.__name__}'
        except Exception as e: return f'validation {i} raised {e!r}'
    return None


def _call(llm, doc, prompt, schema, validations, retries, model, tag, rendered=False):
    """One document through the LLM with DocETL's retry protocol: the failed answer and the failure
    are appended to the conversation and the model is asked again; after `retries` failures the
    document yields None (DocETL drops it)."""
    base = (prompt if rendered else render(prompt, input=doc)) + '\n\nReply with a JSON object with exactly this schema: ' + _schema_text(schema)
    messages = [{'role': 'user', 'content': base}]
    for attempt in range(retries + 1):
        try: res = llm.chat_json(messages, model=model, max_tokens=2000, tag=f'extract.{tag}', retries=0)   # retries are the protocol below
        except ValueError as e:
            res = None; err = f'unparseable reply: {e}'
        else:
            err = validate_output_types(res, schema) or _validate(doc, res, validations)
        if err is None: return res
        messages = messages + [{'role': 'assistant', 'content': json.dumps(res, ensure_ascii=False) if res is not None else ''},
                               {'role': 'user', 'content': f'Your previous response failed validation: {err}. Please try again.'}]
    return None


def map_op(llm: BaseLLM, docs: Sequence[Doc], prompt: str, schema: Dict[str, str], *, validations: Sequence[Callable] = (),
           retries: int = 2, model: Optional[str] = None, drop_keys: Sequence[str] = (), tag: str = 'map',
           skip_on_error: bool = True) -> List[Doc]:
    """LLM projection per document; output keys are added to the document (Sec. 2.2.1).
    Outputs are type-checked against the schema and the user validations (Python predicates
    (doc, output) -> bool); a failure retries with the failure context (Sec. 2.1), and after
    `retries` failures the document is dropped (skip_on_error) or raised."""
    out_docs = []
    for doc in docs:
        result = _call(llm, doc, prompt, schema, validations, retries, model, tag)
        if result is None:
            if skip_on_error: continue
            raise ValueError(f'document failed validation after {retries} retries: {str(doc)[:200]}')
        new = {k: v for k, v in doc.items() if k not in drop_keys}
        new.update({k: result.get(k) for k in schema})
        out_docs.append(new)
    return out_docs


def parallel_map(llm: BaseLLM, docs: Sequence[Doc], prompts: Sequence[Tuple[str, Dict[str, str]]], **kw) -> List[Doc]:
    """Independent projections of the *original* document, merged (Sec. 2.2.1 / directive 11): each
    prompt sees the input document only, never another prompt's output."""
    kw.pop('tag', None)
    results: List[Dict[str, Any]] = [dict(d) for d in docs]
    for i, (prompt, schema) in enumerate(prompts):
        for d, r in zip(docs, results):
            if r is None: continue
            got = _call(llm, d, prompt, schema, kw.get('validations', ()), kw.get('retries', 2), kw.get('model'), f'pmap{i}')
            if got is None:
                for k in schema: r[k] = None
            else: r.update({k: got.get(k) for k in schema})
    return results


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
        peripheral = lambda x: str((x.get(summary_key) if summary_key and x.get(summary_key) is not None else x[f'{key}_chunk']) or '')
        for b in before: parts.append('<context_before>' + peripheral(b) + '</context_before>')
        parts.append('<chunk>' + c[f'{key}_chunk'] + '</chunk>')
        for a in after: parts.append('<context_after>' + peripheral(a) + '</context_after>')
        out.append({**c, f'{key}_rendered': '\n'.join(parts)})
    return out


def _hashable(v):
    return tuple(sorted(map(str, v))) if isinstance(v, (list, set, tuple)) else v


def reduce_op(llm: BaseLLM, docs: Sequence[Doc], keys: Sequence[str], prompt: str, schema: Dict[str, str], *,
              fold_prompt: Optional[str] = None, fold_batch: int = 20, model: Optional[str] = None,
              scratchpad: bool = True, validations: Sequence[Callable] = (), retries: int = 2) -> List[Doc]:
    """Group-by + LLM aggregation with batched folding and a scratchpad (Sec. 2.2.2, Fig. 2).
    One output document per distinct key combination (list-valued keys are folded to tuples).

    A group that fits in one batch is processed with `prompt` alone. Larger groups fold batch by
    batch: `fold_prompt` is rendered with {{ inputs }} (the new batch), {{ output }} (the accumulated
    output, also available as {{ accumulated }}) and {{ reduce_key }}; the model may keep notes in
    `updated_scratchpad` (null unless it is tracking counts or lists across batches, as DocETL instructs),
    which are passed to the next fold. Outputs are type-checked and validated like a map.
    """
    groups: Dict[Tuple, List[Doc]] = defaultdict(list)
    for d in docs: groups[tuple(_hashable(d.get(k)) for k in keys)].append(d)
    out = []
    for kv, items in groups.items():
        reduce_key = dict(zip(keys, kv))
        acc: Optional[Dict[str, Any]] = None; pad: Optional[str] = None
        for b in range(0, len(items), fold_batch):
            batch = items[b:b + fold_batch]
            if acc is None:
                user = render(prompt, inputs=batch, reduce_key=reduce_key)
            else:
                fp = fold_prompt or (prompt + '\n\nYou already produced this output from earlier documents of the group:\n{{ output }}\n'
                                     'Update it with the new documents above so that it reflects all documents seen so far.')
                user = render(fp, inputs=batch, reduce_key=reduce_key, output=acc, accumulated=acc)
            if scratchpad and len(items) > fold_batch:
                user += ('\n\nYou may keep private notes for the next batch in an additional "updated_scratchpad" string field; use it only to '
                         'track counts, frequencies or lists that span batches, otherwise set it to null. Current scratchpad: ' +
                         json.dumps(pad))
            doc = {'_group': reduce_key}
            res = _call(llm, doc, user, schema, validations, retries, model, 'reduce', rendered=True)
            if res is None: continue
            if scratchpad: pad = res.pop('updated_scratchpad', None); pad = None if pad in (None, '', 'null', 'None') else str(pad)
            acc = res
        out.append({**reduce_key, **{k: (acc or {}).get(k) for k in schema}, '_count': len(items)})
    return out


def _norm(s: Any) -> str:
    return re.sub(r'[^0-9a-z]+', ' ', str(s or '').lower()).strip()


def _sim(a: str, b: str) -> float:
    """Cheap blocking score in [0, 1]: token Jaccard, or 1.0 only for strings that are identical
    once case, punctuation and whitespace are removed."""
    if a.replace(' ', '') == b.replace(' ', ''): return 1.0
    ta, tb = set(a.split()), set(b.split())
    if not ta or not tb: return 0.0
    return len(ta & tb) / len(ta | tb)


def resolve(llm: Optional[BaseLLM], docs: Sequence[Doc], key: str, *, comparison_prompt: Optional[str] = None,
            resolution_prompt: Optional[str] = None, blocking_threshold: float = 0.4, model: Optional[str] = None,
            canonical_fn: Optional[Callable[[List[Doc]], str]] = None, context_keys: Sequence[str] = (),
            blocking_conditions: Sequence[Callable[[Doc, Doc], bool]] = ()) -> List[Doc]:
    """Canonicalise variations of `key` across documents (Sec. 2.2.3, directive 9).

    DocETL blocks candidate pairs (embedding similarity tuned for 95% recall, or Python blocking
    conditions), asks the comparison prompt for every surviving pair whose items are still in
    different clusters, unions the matches, and asks the resolution prompt once per cluster for the
    canonical value, which replaces the key in every member document. Here the blocking score is
    token similarity (no embedding model): pairs below `blocking_threshold` and pairs failing any
    `blocking_conditions` are never compared; identical normalised strings merge without an LLM;
    every other candidate pair is decided by the comparison prompt (or merged when llm is None).
    """
    values = [str(d.get(key)) for d in docs if d.get(key) not in (None, '')]
    distinct = sorted(set(values), key=lambda v: (-values.count(v), v))
    rep = {v: next(d for d in docs if str(d.get(key)) == v) for v in distinct}
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
            if any(not cond(rep[a], rep[b]) for cond in blocking_conditions): continue
            if s >= 1.0: same = True
            elif llm is None: same = True
            else:
                da, db = rep[a], rep[b]
                cp = comparison_prompt or ('Do the following two values of "' + key + '" refer to the same entity?\n'
                                           'Value 1: {{ input1.' + key + ' }}\nValue 2: {{ input2.' + key + ' }}')
                user = render(cp, input1=da, input2=db)
                if context_keys: user += '\nContext 1: ' + json.dumps({k: da.get(k) for k in context_keys}, default=str)[:800] + \
                                         '\nContext 2: ' + json.dumps({k: db.get(k) for k in context_keys}, default=str)[:800]
                try: res = llm.json(user + '\n\nReply with JSON: {"same": true|false}', model=model, max_tokens=100, tag='extract.resolve.compare')
                except ValueError: res = None
                same = bool(res.get('same')) if isinstance(res, dict) else False
            if same: parent[find(b)] = find(a)
    groups: Dict[str, List[str]] = defaultdict(list)
    for v in distinct: groups[find(v)].append(v)
    canon: Dict[str, Any] = {}
    for root, members in groups.items():
        if len(members) == 1: continue                       # singletons keep their original value and type
        member_docs = [rep[m] for m in members]
        if canonical_fn is not None: c = canonical_fn(member_docs)
        elif llm is not None:
            rp = resolution_prompt or ('The following values refer to the same entity:\n{{ inputs }}\n'
                                       'Provide one canonical value that best represents them.')
            try: res = llm.json(render(rp, inputs=member_docs) + '\n\nReply with JSON: {"' + key + '": "..."}', model=model,
                                max_tokens=200, tag='extract.resolve.canonical')
            except ValueError: res = None
            c = res.get(key) if isinstance(res, dict) and res.get(key) else members[0]
        else: c = members[0]
        for m in members: canon[m] = c
    out = []
    for d in docs:
        v = d.get(key)
        if v in (None, '') or str(v) not in canon: out.append(dict(d))
        else: out.append({**d, key: canon[str(v)], f'{key}_original': v})
    return out
