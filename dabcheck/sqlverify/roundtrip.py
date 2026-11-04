"""Round-Trip Critique (Sec. 3.2): s -> q' (isolated from q), then C(q, q') on a 1-5 Likert scale."""
from __future__ import annotations
from typing import Any, Dict, Optional

from ..llm import BaseLLM
from .schema import Schema, render_schema

LIKERT = """Score the semantic alignment of the two questions:
5 = identical intent: same population, filters, time window, aggregation, grouping, ranking and output.
4 = equivalent except for wording or an immaterial presentation detail.
3 = mostly aligned but one requested element differs (an extra or missing column, a loosened filter).
2 = partially aligned: a different population, time window, aggregation or ranking basis.
1 = different questions."""


def back_translate(llm: BaseLLM, sql: str, schema: Schema, model: Optional[str] = None) -> str:
    """R(s, d): describe exactly what the query computes as a natural-language question. The original
    question is deliberately not provided."""
    user = (f'Schema:\n{render_schema(schema)}\n\nSQL:\n{sql}\n\n'
            'Write the natural-language question this query answers. Be literal and complete: name the population '
            '(tables, joins, filters), the exact time window and which date column it applies to, the aggregation and '
            'its denominator, grouping, ordering/limit, and the output columns. Do not guess intent beyond the query. '
            'Reply with JSON: {"question": "..."}')
    out = llm.json(user, model=model, max_tokens=800, tag='sqlverify.rt.back')
    return str(out.get('question', '')) if isinstance(out, dict) else str(out)


def critique_questions(llm: BaseLLM, question: str, generated: str, model: Optional[str] = None) -> Dict[str, Any]:
    user = (f'Original question:\n{question}\n\nQuestion reconstructed from the SQL:\n{generated}\n\n{LIKERT}\n\n'
            'List every concrete semantic difference (population, filter, time window / date field, aggregation, denominator, '
            'ranking metric, output columns) before scoring. Reply with JSON: {"differences": ["..."], "score": n}')
    out = llm.json(user, model=model, max_tokens=800, tag='sqlverify.rt.critique')
    if not isinstance(out, dict): out = {'score': 1, 'differences': ['unparseable critique']}
    try: out['score'] = int(out.get('score', 1))
    except (TypeError, ValueError): out['score'] = 1
    return out


def round_trip_verify(llm: BaseLLM, question: str, sql: str, schema: Schema, *, tau: int = 4, model: Optional[str] = None) -> Dict[str, Any]:
    q2 = back_translate(llm, sql, schema, model)
    c = critique_questions(llm, question, q2, model)
    return {'method': 'round_trip', 'accept': c['score'] >= tau, 'score': c['score'], 'threshold': tau,
            'back_translation': q2, 'differences': c.get('differences', []),
            'reason': f"round-trip score {c['score']}/5" + ('' if c['score'] >= tau else ': ' + '; '.join([str(x) for x in c.get('differences', [])][:3]))}
