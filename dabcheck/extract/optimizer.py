"""Agentic plan rewriting and evaluation (DocETL Sec. 4), compact version.

- synthesize_validation: a validation agent writes task-specific criteria for an operation.
- needs_improvement: the agent judges a few sample input/output pairs against the criteria
  (the gate that decides whether rewriting is attempted at all).
- rate_outputs: the agent rates each sample output against the criteria (1-5), averaged per plan.
- rewrite_map: generation agents instantiate directives for a map: chaining (10), isolating
  (11), gleaning (7); each returns a runnable plan (callable docs -> docs).
- optimize_map: run candidate plans on a sample, rate them, pairwise-compare the top plans
  (DocETL: 6; one win per pair), return the winner (opportunistic: the original is kept when
  the validation agent is satisfied).
"""
from __future__ import annotations
import itertools, json
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from ..llm import BaseLLM
from .ops import map_op, parallel_map, render, Doc
from .gleaning import glean

Plan = Callable[[Sequence[Doc]], List[Doc]]


def synthesize_validation(llm: BaseLLM, prompt: str, schema: Dict[str, str], sample: Sequence[Doc] = (), outputs: Sequence[Doc] = (),
                          model: Optional[str] = None) -> List[str]:
    """Validation agent (Sec. 4.1, DocETL prompt_generators): task-specific criteria written after
    looking at the operation and a sample input/output, testing precision ("every item exists in the
    document") and recall ("nothing in the document is missed"), not prompt adherence."""
    shown = ''
    if sample and outputs:
        d, o = sample[0], outputs[0]
        shown = ('\n\nSample input:\n' + json.dumps(d, ensure_ascii=False, default=str)[:4000] + '\nSample output:\n' +
                 json.dumps({k: o.get(k) for k in schema}, ensure_ascii=False, default=str)[:2000])
    user = ('An LLM operation is defined by this prompt template and output schema.\nPrompt:\n' + prompt +
            '\nSchema: ' + json.dumps(schema) + shown +
            '\n\nWrite 2-4 specific validation criteria that test the accuracy, precision and recall of its outputs '
            '(e.g. "every listed instance exists in the document", "no instance in the document is missing"). '
            'Reply with JSON: {"criteria": ["..."]}')
    out = llm.json(user, model=model, max_tokens=800, tag='extract.opt.criteria')
    return [str(c) for c in out.get('criteria', [])] if isinstance(out, dict) else []


def needs_improvement(llm: BaseLLM, criteria: Sequence[str], docs: Sequence[Doc], outputs: Sequence[Doc], schema: Dict[str, str],
                      model: Optional[str] = None, max_docs: int = 3) -> Dict[str, Any]:
    """The validation agent's gate (DocETL evaluator._assess_operation): one judgement over up to
    three sample input/output pairs -> {needs_improvement, reasons}."""
    pairs = []
    for d, o in list(zip(docs, outputs))[:max_docs]:
        pairs.append('Input:\n' + json.dumps(d, ensure_ascii=False, default=str)[:3000] + '\nOutput:\n' +
                     json.dumps({k: o.get(k) for k in schema}, ensure_ascii=False, default=str)[:2000])
    user = ('Criteria:\n' + '\n'.join('- ' + c for c in criteria) + '\n\n' + '\n\n'.join(pairs) +
            '\n\nDo these outputs fall short of the criteria in a way that a decomposed or refined operation could fix? '
            'Reply with JSON: {"needs_improvement": true|false, "reasons": ["..."]}')
    out = llm.json(user, model=model, max_tokens=600, tag='extract.opt.assess')
    if not isinstance(out, dict): out = {'needs_improvement': True, 'reasons': ['unparseable assessment']}
    return {'needs_improvement': bool(out.get('needs_improvement')), 'reasons': out.get('reasons', [])}


def rate_outputs(llm: BaseLLM, criteria: Sequence[str], docs: Sequence[Doc], outputs: Sequence[Doc], schema: Dict[str, str],
                 model: Optional[str] = None) -> Dict[str, Any]:
    """Per-document ratings against the criteria, averaged per plan (Sec. 4.1 step 3, first stage)."""
    ratings = []
    for d, o in zip(docs, outputs):
        user = ('Document:\n' + json.dumps(d, ensure_ascii=False, default=str)[:6000] + '\n\nOutput:\n' +
                json.dumps({k: o.get(k) for k in schema}, ensure_ascii=False, default=str)[:3000] +
                '\n\nCriteria:\n' + '\n'.join('- ' + c for c in criteria) +
                '\n\nRate the output from 1 (fails most criteria) to 5 (meets all). Reply with JSON: {"rating": n, "issues": ["..."]}')
        r = llm.json(user, model=model, max_tokens=500, tag='extract.opt.rate')
        ratings.append(r if isinstance(r, dict) else {'rating': 1})
    avg = sum(float(r.get('rating', 1)) for r in ratings) / max(1, len(ratings))
    return {'average': avg, 'ratings': ratings}


def rewrite_map(llm: BaseLLM, prompt: str, schema: Dict[str, str], sample: Sequence[Doc], *, model: Optional[str] = None,
                directives: Sequence[str] = ('chaining', 'isolating', 'gleaning'), criteria: Sequence[str] = ()) -> Dict[str, Plan]:
    """Candidate plans for a map operation; each directive is instantiated by a generation agent.
    The gleaning plan uses the validation criteria already synthesised for the operation."""
    plans: Dict[str, Plan] = {}
    plans['original'] = lambda docs: map_op(llm, docs, prompt, schema, model=model, tag='orig')
    if 'gleaning' in directives:
        vprompt = ' '.join(criteria) or 'Is the output complete and supported by the document?'
        plans['gleaning'] = lambda docs: [{**d, **glean(llm, d, prompt, schema, validation_prompt=vprompt, model=model, max_rounds=1)} for d in docs]
    for directive in ('chaining', 'isolating'):
        if directive not in directives: continue
        user = ('Rewrite this LLM map operation using the "' + directive + '" directive.\n'
                + ('Chaining: a sequence of simpler map prompts where each builds on the previous output; the last one produces the schema.\n'
                   if directive == 'chaining' else
                   'Isolating: several independent map prompts, each producing a disjoint subset of the schema keys, run in parallel.\n')
                + 'Original prompt (Jinja-style, {{ input.<key> }} refers to document fields):\n' + prompt +
                '\nOutput schema: ' + json.dumps(schema) +
                '\nSample document keys: ' + json.dumps(sorted(sample[0].keys()) if sample else []) +
                '\n\nReply with JSON: {"steps": [{"prompt": "...", "output_keys": ["..."]}]} where every prompt keeps the {{ input.<key> }} '
                'placeholders and, for chaining, later steps may reference keys produced by earlier steps as {{ input.<key> }}.')
        try:
            spec = llm.json(user, model=model, max_tokens=2000, tag=f'extract.opt.rewrite.{directive}')
            steps = []
            for st in spec.get('steps', []):
                if not isinstance(st, dict) or not st.get('prompt'): continue
                keys = st.get('output_keys') or list((st.get('schema') or {}).keys())
                step_schema = {k: schema.get(k, 'string') for k in keys}   # types come from the original schema
                if step_schema: steps.append((st['prompt'], step_schema))
        except Exception: steps = []
        if not steps or not all('{{' in p for p, _ in steps): continue   # every step must reference the document
        if directive == 'isolating':
            covered = {k for _, sc in steps for k in sc}
            missing = [k for k in schema if k not in covered]
            if missing:   # DocETL adds uncovered keys to the closest subtask; here to the last one
                steps[-1] = (steps[-1][0], {**steps[-1][1], **{k: schema[k] for k in missing}})
            plans['isolating'] = (lambda st: (lambda docs: parallel_map(llm, docs, st, model=model)))(steps)
        else:
            if any(k not in steps[-1][1] for k in schema):   # the chain must end with the full schema
                steps[-1] = (steps[-1][0], {**steps[-1][1], **schema})
            plans['chaining'] = (lambda st: (lambda docs: _chain(llm, docs, st, schema, model)))(steps)
    return plans


def _chain(llm, docs, steps, schema, model):
    cur = list(docs)
    for i, (p, s) in enumerate(steps): cur = map_op(llm, cur, p, s, model=model, tag=f'chain{i}')
    return [{**d, **{k: d.get(k) for k in schema}} for d in cur]


def optimize_map(llm: BaseLLM, prompt: str, schema: Dict[str, str], sample: Sequence[Doc], *, model: Optional[str] = None,
                 top_k: int = 6, directives: Sequence[str] = ('chaining', 'isolating', 'gleaning')) -> Dict[str, Any]:
    """Opportunistic optimisation of one map (Sec. 4.1): run the original on the sample; the
    validation agent writes criteria from a sample output and judges whether the operation needs
    improvement; if not, keep it. Otherwise generate rewrites, rate every plan's outputs on the
    sample, keep the top `top_k` (DocETL: 6) and compare them pairwise: each pair gives one win to
    the plan that won on more documents; the plan with the most wins is selected."""
    orig = map_op(llm, sample, prompt, schema, model=model, tag='orig')
    criteria = synthesize_validation(llm, prompt, schema, sample, orig, model)
    gate = needs_improvement(llm, criteria, sample, orig, schema, model)
    if not gate['needs_improvement']:
        return {'plan': 'original', 'criteria': criteria, 'assessment': gate, 'outputs': {'original': orig}}
    plans = rewrite_map(llm, prompt, schema, sample, model=model, directives=directives, criteria=criteria)
    outputs = {'original': orig}; ratings = {'original': rate_outputs(llm, criteria, sample, orig, schema, model)['average']}
    for name, plan in plans.items():
        if name == 'original': continue
        try: outputs[name] = plan(sample)
        except Exception: continue
        ratings[name] = rate_outputs(llm, criteria, sample, outputs[name], schema, model)['average']
    top = sorted(ratings, key=ratings.get, reverse=True)[:top_k]
    wins = {n: 0 for n in top}
    for a, b in itertools.combinations(top, 2):
        doc_wins = {a: 0, b: 0}
        for d, oa, ob in zip(sample, outputs[a], outputs[b]):
            user = ('Document:\n' + json.dumps(d, ensure_ascii=False, default=str)[:5000] + '\n\nOutput A:\n' +
                    json.dumps({k: oa.get(k) for k in schema}, default=str)[:2500] + '\n\nOutput B:\n' +
                    json.dumps({k: ob.get(k) for k in schema}, default=str)[:2500] + '\n\nCriteria:\n' + '\n'.join('- ' + c for c in criteria) +
                    '\n\nWhich output is better? Reply with JSON: {"winner": "A" | "B" | "tie"}')
            r = llm.json(user, model=model, max_tokens=100, tag='extract.opt.pairwise')
            w = r.get('winner') if isinstance(r, dict) else 'tie'
            if w == 'A': doc_wins[a] += 1
            elif w == 'B': doc_wins[b] += 1
        if doc_wins[a] > doc_wins[b]: wins[a] += 1
        elif doc_wins[b] > doc_wins[a]: wins[b] += 1
    best = max(top, key=lambda n: (wins[n], ratings[n]))
    return {'plan': best, 'criteria': criteria, 'assessment': gate, 'ratings': ratings, 'wins': wins, 'outputs': outputs}
