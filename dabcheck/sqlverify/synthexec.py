"""Synthetic Execution Consistency (Sec. 3.3): unit-test-like verification of a SQL query."""
from __future__ import annotations
import json, math, re, sqlite3
from typing import Any, Dict, List, Optional, Sequence, Tuple

from ..llm import BaseLLM
from .schema import Schema, render_schema

SYSTEM = ('You build small test databases to check whether a SQL query answers a question. '
          'Return only data that fits the given schema; include edge cases (ties, nulls, boundary dates, duplicates, '
          'rows that must be excluded). The expected answer must contain only what the question asks for.')


def synthesize_cases(llm: BaseLLM, question: str, schema: Schema, *, mode: str = 'answer_first', n_cases: int = 2,
                     model: Optional[str] = None, sql: Optional[str] = None) -> List[Dict[str, Any]]:
    """Answer-first: invent answers then a DB that makes them true. Data-first: invent a DB state
    then deduce the answer. The candidate SQL is not shown to the generator (independence)."""
    shape = {'cases': [{'tables': {'<table>': [{'<column>': '<value>'}]}, 'expected': '<scalar, or list of rows (lists)>', 'note': '<what this case tests>'}]}
    if mode == 'answer_first':
        how = (f'For each of {n_cases} test cases: first invent a plausible, distinct answer to the question; then construct a '
               'minimal database instance (5-15 rows per relevant table, every referenced table present) for which that '
               'answer is exactly correct. Include rows that a wrong query would wrongly include or exclude.')
    else:
        how = (f'For each of {n_cases} test cases: first construct a small but tricky database instance (5-15 rows per relevant '
               'table, every referenced table present); then work out the exact correct answer to the question on it.')
    user = (f'Question: {question}\n\nSchema:\n{render_schema(schema)}\n\n{how}\n'
            'Dates must be ISO strings; numbers plain numbers; use null for missing. '
            'Reply with JSON of this shape: ' + json.dumps(shape))
    out = llm.json(user, SYSTEM, model=model, max_tokens=6000, tag=f'sqlverify.se.{mode}')
    cases = out.get('cases') if isinstance(out, dict) else None
    good = []
    for c in cases or []:
        if isinstance(c, dict) and isinstance(c.get('tables'), dict) and 'expected' in c:
            good.append({'tables': c['tables'], 'expected': c['expected'], 'note': c.get('note', ''), 'mode': mode})
    return good


def _transpile(sql: str, dialect: str) -> str:
    if dialect in ('sqlite', '', None): return sql
    try:
        import sqlglot
        out = sqlglot.transpile(sql, read=dialect, write='sqlite')[0]
    except Exception:
        return sql
    if sqlite3.sqlite_version_info < (3, 30):   # NULLS FIRST/LAST needs sqlite >= 3.30
        out = re.sub(r'\s+NULLS\s+(FIRST|LAST)\b', '', out, flags=re.I)
    return out


def execute_sql(schema: Schema, tables: Dict[str, List[Dict[str, Any]]], sql: str, dialect: Optional[str] = None) -> Dict[str, Any]:
    """Load the synthetic rows into an in-memory sqlite database and run the query."""
    con = sqlite3.connect(':memory:')
    try:
        for ddl in schema.ddl_sqlite(): con.execute(ddl)
        for tname, rows in tables.items():
            t = schema.tables.get(tname) or next((x for x in schema.tables.values() if x.name.lower() == tname.lower()), None)
            if t is None:   # unknown table in the synthetic data: create it from the rows
                cols = sorted({k for r in rows for k in r}) if rows else []
                if not cols: continue
                con.execute(f'CREATE TABLE "{tname}" (' + ', '.join(f'"{c}"' for c in cols) + ')')
                names = cols; real = tname
            else: names = t.column_names(); real = t.name
            for r in rows:
                if not isinstance(r, dict): continue
                vals = [r.get(c) for c in names]
                vals = [json.dumps(v) if isinstance(v, (list, dict)) else v for v in vals]
                con.execute(f'INSERT INTO "{real}" (' + ', '.join(f'"{c}"' for c in names) + ') VALUES (' + ','.join('?' * len(names)) + ')', vals)
        q = _transpile(sql, dialect or schema.dialect)
        try: cur = con.execute(q)
        except sqlite3.Error:
            if q == sql: raise
            q = sql; cur = con.execute(q)   # the transpiled form failed; try the query as written
        cols = [d[0] for d in cur.description] if cur.description else []
        rows = cur.fetchall()
        return {'columns': cols, 'rows': [list(r) for r in rows], 'sql_executed': q}
    except Exception as e:
        return {'error': f'{type(e).__name__}: {e}', 'columns': [], 'rows': []}
    finally: con.close()


def _scalar(v: Any) -> Any:
    if v is None: return None
    if isinstance(v, bool): return int(v)
    if isinstance(v, (int, float)):
        if isinstance(v, float) and (math.isnan(v) or math.isinf(v)): return None
        return round(float(v), 6)
    s = str(v).strip()
    try:
        if re.fullmatch(r'-?\d+(?:\.\d+)?', s.replace(',', '')): return round(float(s.replace(',', '')), 6)
    except ValueError: pass
    return s.lower()


def normalize_result(value: Any) -> List[Tuple[Any, ...]]:
    """Any answer shape -> sorted multiset of tuples (order-insensitive comparison; Sec. 4.2)."""
    if value is None: return [(None,)]
    if isinstance(value, dict):
        if 'rows' in value and isinstance(value['rows'], list): return normalize_result(value['rows'])
        return [tuple(_scalar(v) for v in value.values())]
    if isinstance(value, (list, tuple)):
        if not value: return []
        if all(isinstance(x, (list, tuple)) for x in value): rows = [tuple(_scalar(v) for v in x) for x in value]
        elif all(isinstance(x, dict) for x in value): rows = [tuple(_scalar(v) for v in x.values()) for x in value]
        else: rows = [(_scalar(x),) for x in value]
        return sorted(rows, key=lambda r: json.dumps(r, default=str))
    return [(_scalar(value),)]


def results_match(expected: Any, actual_rows: Sequence[Sequence[Any]], ordered: bool = False) -> bool:
    """Equality up to ordering, number formatting and case; a scalar expected value also matches
    a single-cell result and a result whose rows all equal it in one column."""
    e = normalize_result(expected); a = normalize_result([list(r) for r in actual_rows])
    if ordered and e == a: return True
    if e == a: return True
    if len(e) == 1 and len(e[0]) == 1:               # scalar expected
        ev = e[0][0]
        if len(a) == 1 and ev in a[0]: return True
        if len(a) >= 1 and all(len(r) == 1 for r in a) and len(a) == 1: return a[0][0] == ev
    if len(e) == len(a) and all(len(r) >= 1 for r in e):   # expected is a projection of the actual columns
        try:
            if all(set(er) <= set(ar) for er, ar in zip(e, a)): return True
        except TypeError: pass
    return False


def synthetic_execution_verify(llm: BaseLLM, question: str, sql: str, schema: Schema, *, n_cases: int = 2,
                               modes: Sequence[str] = ('answer_first',), model: Optional[str] = None,
                               cases: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """v_se = 1 iff the query reproduces the expected answer on every synthetic test case."""
    if cases is None:
        cases = []
        for m in modes: cases += synthesize_cases(llm, question, schema, mode=m, n_cases=n_cases, model=model)
    results = []
    for c in cases:
        ex = execute_sql(schema, c['tables'], sql)
        ok = ('error' not in ex) and results_match(c['expected'], ex['rows'])
        results.append({'note': c.get('note', ''), 'mode': c.get('mode'), 'expected': c['expected'], 'actual': ex.get('rows'),
                        'error': ex.get('error'), 'match': ok})
    n_fail = sum(1 for r in results if not r['match'])
    return {'method': 'synthetic_execution', 'accept': bool(results) and n_fail == 0, 'cases': results,
            'n_cases': len(results), 'n_failed': n_fail,
            'reason': 'no test cases' if not results else (f'{n_fail} of {len(results)} synthetic cases disagree' if n_fail else 'all synthetic cases agree')}
