"""Direct critique baseline (Sec. 3.1; TrustSQL's ERROR_P): one LLM judgement on (q, s, d)."""
from __future__ import annotations
from typing import Any, Dict, Optional

from ..llm import BaseLLM
from .schema import Schema, render_schema


def sql_critique(llm: BaseLLM, question: str, sql: str, schema: Schema, model: Optional[str] = None) -> Dict[str, Any]:
    user = (f'Question:\n{question}\n\nSchema:\n{render_schema(schema)}\n\nSQL:\n{sql}\n\n'
            'Does the SQL correctly answer the question on this schema? Check tables and joins, filters, the date column '
            'and window, aggregation and grouping, ranking and the output. Be strict. '
            'Reply with JSON: {"correct": true|false, "reason": "..."}')
    out = llm.json(user, model=model, max_tokens=600, tag='sqlverify.sc')
    ok = bool(out.get('correct')) if isinstance(out, dict) else False
    return {'method': 'sql_critique', 'accept': ok, 'reason': str(out.get('reason', '')) if isinstance(out, dict) else 'unparseable'}
