"""Agentic plan rewriting and evaluation (DocETL Sec. 4), compact version.

- synthesize_validation: a validation agent writes task-specific criteria for an operation.
- rate_outputs: the agent rates sample outputs against those criteria (1-5) and says whether
  the operation needs rewriting.
- rewrite_map: generation agents instantiate directives for a map: chaining (10), isolating
  (11), gleaning (7); each returns a runnable plan (callable docs -> docs).
- optimize_map: run candidate plans on a sample, rate them, pairwise-compare the top plans,
  return the winner (opportunistic: the original is kept when the validator is satisfied).
"""
from __future__ import annotations
import itertools, json
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from ..llm import BaseLLM
from .ops import map_op, parallel_map, render, Doc
from .gleaning import glean

Plan = Callable[[Sequence[Doc]], List[Doc]]


def synthesize_validation(llm: BaseLLM, prompt: str, schema: Dict[str, str], model: Optional[str] = None) -> List[str]:
    user = ('An LLM operation is defined by this prompt template and output schema.\nPrompt:\n' + prompt +
            '\nSchema: ' + json.dumps(schema) +
            '\n\nWrite 3-5 specific validation criteria that test the accuracy, precision and recall of its outputs '
            '(e.g. "every listed instance exists in the document", "no instance in the document is missing"). '
            'Reply with JSON: {"criteria": ["..."]}')
    out = llm.json(user, model=model, max_tokens=800, tag='extract.opt.criteria')
    return [str(c) for c in out.get('criteria', [])] if isinstance(out, dict) else []


def rate_outputs(llm: BaseLLM, criteria: Sequence[str], docs: Sequence[Doc], outputs: Sequence[Doc], schema: Dict[str, str],
                 model: Optional[str] = None) -> Dict[str, Any]:
    ratings = []
    for d, o in zip(docs, outputs):
        user = ('Document:\n' + json.dumps(d, ensure_ascii=False, default=str)[:6000] + '\n\nOutput:\n' +
                json.dumps({k: o.get(k) for k in schema}, ensure_ascii=False, default=str)[:3000] +
                '\n\nCriteria:\n' + '\n'.join('- ' + c for c in criteria) +
                '\n\nRate the output from 1 (fails most criteria) to 5 (meets all). Reply with JSON: {"rating": n, "issues": ["..."]}')
        r = llm.json(user, model=model, max_tokens=500, tag='extract.opt.rate')
        ratings.append(r if isinstance(r, dict) else {'rating': 1})
    avg = sum(float(r.get('rating', 1)) for r in ratings) / max(1, len(ratings))
    return {'average': avg, 'ratings': ratings, 'satisfactory': avg >= 4.5}


def rewrite_map(llm: BaseLLM, prompt: str, schema: Dict[str, str], sample: Sequence[Doc], *, model: Optional[str] = None,
                directives: Sequence[str] = ('chaining', 'isolating', 'gleaning')) -> Dict[str, Plan]:
    """Candidate plans for a map operation. Each directive is instantiated by the LLM."""
    plans: Dict[str, Plan] = {}
    plans['original'] = lambda docs: map_op(llm, docs, prompt, schema, model=model, tag='orig')
    if 'gleaning' in directives:
        vp = synthesize_validation(llm, prompt, schema, model)
        vprompt = ' '.join(vp) or 'Is the output complete and supported by the document?'
        plans['gleaning'] = lambda docs: [{**d, **glean(llm, d, prompt, schema, validation_prompt=vprompt, model=model)} for d in docs]
    for directive in ('chaining', 'isolating'):
        if directive not in directives: continue
        user = ('Rewrite this LLM map operation using the "' + directive + '" directive.\n'
                + ('Chaining: a sequence of simpler map prompts where each builds on the previous output; the last one produces the schema.\n'
                   if directive == 'chaining' else
                   'Isolating: several independent map prompts, each producing a disjoint subset of the schema keys, run in parallel.\n')
                + 'Original prompt (Jinja-style, {{ input.<key> }} refers to document fields):\n' + prompt +
                '\nOutput schema: ' + json.dumps(schema) +
                '\nSample document keys: ' + json.dumps(sorted(sample[0].keys()) if sample else []) +
                '\n\nReply with JSON: {"steps": [{"prompt": "...", "schema": {...}}]} where every prompt keeps the {{ input.<key> }} '
                'placeholders and later steps may reference keys produced by earlier steps.')
        try:
            spec = llm.json(user, model=model, max_tokens=2000, tag=f'extract.opt.rewrite.{directive}')
            steps = [(s['prompt'], s['schema']) for s in spec.get('steps', []) if isinstance(s, dict) and s.get('prompt') and s.get('schema')]
        except Exception: steps = []
        if not steps or '{{' not in ''.join(p for p, _ in steps): continue   # the paper's critical error: no placeholder
        if directive == 'chaining':
            plans['chaining'] = (lambda st: (lambda docs: _chain(llm, docs, st, schema, model)))(steps)
        else:
            plans['isolating'] = (lambda st: (lambda docs: parallel_map(llm, docs, st, model=model)))(steps)
    return plans


def _chain(llm, docs, steps, schema, model):
    cur = list(docs)
    for i, (p, s) in enumerate(steps): cur = map_op(llm, cur, p, s, model=model, tag=f'chain{i}')
    return [{**d, **{k: d.get(k) for k in schema}} for d in cur]


def optimize_map(llm: BaseLLM, prompt: str, schema: Dict[str, str], sample: Sequence[Doc], *, model: Optional[str] = None,
                 top_k: int = 3, directives: Sequence[str] = ('chaining', 'isolating', 'gleaning')) -> Dict[str, Any]:
    """Opportunistic optimisation of one map: keep the original when it rates as satisfactory,
    else evaluate rewrites on the sample (ratings, then pairwise comparisons of the top plans)."""
    criteria = synthesize_validation(llm, prompt, schema, model)
    orig = map_op(llm, sample, prompt, schema, model=model, tag='orig')
    base = rate_outputs(llm, criteria, sample, orig, schema, model)
    if base['satisfactory']:
        return {'plan': 'original', 'criteria': criteria, 'ratings': {'original': base['average']}, 'outputs': {'original': orig}}
    plans = rewrite_map(llm, prompt, schema, sample, model=model, directives=directives)
    outputs = {'original': orig}; ratings = {'original': base['average']}
    for name, plan in plans.items():
        if name == 'original': continue
        try: outputs[name] = plan(sample)
        except Exception: continue
        ratings[name] = rate_outputs(llm, criteria, sample, outputs[name], schema, model)['average']
    top = sorted(ratings, key=ratings.get, reverse=True)[:top_k]
    wins = {n: 0 for n in top}
    for a, b in itertools.combinations(top, 2):
        for d, oa, ob in zip(sample, outputs[a], outputs[b]):
            user = ('Document:\n' + json.dumps(d, ensure_ascii=False, default=str)[:5000] + '\n\nOutput A:\n' +
                    json.dumps({k: oa.get(k) for k in schema}, default=str)[:2500] + '\n\nOutput B:\n' +
                    json.dumps({k: ob.get(k) for k in schema}, default=str)[:2500] + '\n\nCriteria:\n' + '\n'.join('- ' + c for c in criteria) +
                    '\n\nWhich output is better? Reply with JSON: {"winner": "A" | "B" | "tie"}')
            r = llm.json(user, model=model, max_tokens=100, tag='extract.opt.pairwise')
            w = r.get('winner') if isinstance(r, dict) else 'tie'
            if w == 'A': wins[a] += 1
            elif w == 'B': wins[b] += 1
    best = max(top, key=lambda n: (wins[n], ratings[n]))
    return {'plan': best, 'criteria': criteria, 'ratings': ratings, 'wins': wins, 'outputs': outputs}
