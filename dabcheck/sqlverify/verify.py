"""Combine verifiers (Sec. 5.2.4) and selective generation (Sec. 7)."""
from __future__ import annotations
from typing import Any, Callable, Dict, List, Optional, Sequence

from ..llm import BaseLLM
from .schema import Schema
from .roundtrip import round_trip_verify
from .synthexec import synthetic_execution_verify
from .critique import sql_critique
from .cohort import cohort_check

METHODS = {'rt': round_trip_verify, 'se': synthetic_execution_verify, 'sc': sql_critique, 'cohort': cohort_check}


def verify_sql(llm: BaseLLM, question: str, sql: str, schema: Schema, *, methods: Sequence[str] = ('rt', 'se'),
               combine: str = 'and', tau: int = 4, n_cases: int = 2, model: Optional[str] = None) -> Dict[str, Any]:
    """Run the chosen verifiers; AND = every verifier must accept (conservative, lowest false-accept
    rate in the paper), OR = any acceptance suffices (permissive)."""
    results = {}
    for m in methods:
        if m == 'rt': results[m] = round_trip_verify(llm, question, sql, schema, tau=tau, model=model)
        elif m == 'se': results[m] = synthetic_execution_verify(llm, question, sql, schema, n_cases=n_cases, model=model)
        elif m == 'sc': results[m] = sql_critique(llm, question, sql, schema, model=model)
        elif m == 'cohort': results[m] = cohort_check(llm, question, sql, schema, model=model)
        else: raise ValueError(m)
    votes = [r['accept'] for r in results.values()]
    accept = all(votes) if combine == 'and' else any(votes)
    reasons = [f"{m}: {'accept' if r['accept'] else 'reject'} ({r.get('reason', '')})" for m, r in results.items()]
    return {'accept': accept, 'combine': combine, 'methods': results, 'reasons': reasons}


def selective(generate: Callable[[str], str], llm: BaseLLM, question: str, schema: Schema, **kw) -> Dict[str, Any]:
    """Selective generator: produce SQL, verify it, abstain when rejected (coverage vs selective accuracy)."""
    sql = generate(question)
    v = verify_sql(llm, question, sql, schema, **kw)
    return {'sql': sql if v['accept'] else None, 'abstained': not v['accept'], 'verification': v}
