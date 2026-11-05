"""Harness-side pieces of the three method conditions (one per failure category).

fdj        identifier joins   : dataset-level FDJ outputs staged read-only into the task directory
docetl     extraction         : dataset-level DocETL extraction outputs staged the same way
sqlverify  cohort / temporal  : round 1 unchanged; the SQL the agent ran is verified harness-side
                                (round trip + synthetic execution + cohort cards, AND); on a rejection
                                a second session gets the warnings and its answer is graded
All LLM calls made here use one model (the agent's model, Haiku), enforced by dabcheck.llm.LLM.
"""
from __future__ import annotations
import json, re, shutil, stat
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

METHODS = ('fdj', 'docetl', 'sqlverify')
PREP_DIRNAME = 'dabcheck_prep'

ADDENDUM = {
    'fdj': ('PRECOMPUTED JOINS (experimental condition "fdj"): before your session, a semantic join method (FDJ) was run '
            'on the noisy identifier / entity columns of this dataset. Its outputs are in ./{d}/ ; read ./{d}/README.md first. '
            'They are machine-generated and may contain errors.'),
    'docetl': ('PRECOMPUTED EXTRACTIONS (experimental condition "docetl"): before your session, an LLM extraction pipeline (DocETL) '
               'was run on the text columns of this dataset that hold numbers or names. Its outputs are in ./{d}/ ; read ./{d}/README.md '
               'first. They are machine-generated and may contain errors.'),
}


def prep_dir(prep_root: Path, method: str, dataset: str) -> Path:
    return Path(prep_root) / method / dataset


def has_prep(prep_root: Path, method: str, dataset: str) -> bool:
    """True when the dataset has at least one usable output (a CSV listed in MANIFEST.json)."""
    m = prep_dir(prep_root, method, dataset) / 'MANIFEST.json'
    if not m.exists(): return False
    specs = json.loads(m.read_text()).get('specs', {})
    return any(v.get('csv') and v.get('status') in ('ok', 'partial') for v in specs.values())


def stage_prep(prep_root: Path, method: str, dataset: str, work: Path) -> Optional[Path]:
    """Copy the dataset's README and CSV outputs into <work>/dabcheck_prep (read-only); None if nothing usable."""
    if not has_prep(prep_root, method, dataset): return None
    src = prep_dir(prep_root, method, dataset)
    specs = json.loads((src / 'MANIFEST.json').read_text())['specs']
    dest = Path(work) / PREP_DIRNAME
    if dest.exists():
        for p in dest.rglob('*'): p.chmod(stat.S_IRUSR | stat.S_IWUSR | (stat.S_IXUSR if p.is_dir() else 0))
        shutil.rmtree(dest)
    dest.mkdir()
    shutil.copyfile(src / 'README.md', dest / 'README.md')
    for v in specs.values():
        if v.get('csv') and v.get('status') in ('ok', 'partial'): shutil.copyfile(src / v['csv'], dest / v['csv'])
    for p in dest.iterdir(): p.chmod(stat.S_IRUSR)
    return dest


def prompt_addendum(method: str) -> str:
    return ADDENDUM[method].format(d=PREP_DIRNAME)


# ---------------------------------------------------------------- sqlverify

_TABLE = re.compile(r'\b(?:FROM|JOIN)\s+("?[\w.]+"?)', re.I)


def tables_in(sql: str) -> List[str]:
    try:
        import sqlglot
        from sqlglot import exp
        names = []
        for stmt in sqlglot.parse(sql, error_level=sqlglot.ErrorLevel.IGNORE):
            if stmt is None: continue
            ctes = {c.alias_or_name for c in stmt.find_all(exp.CTE)}
            names += [t.name for t in stmt.find_all(exp.Table) if t.name and t.name not in ctes]
        if names: return list(dict.fromkeys(names))
    except Exception: pass
    return list(dict.fromkeys(m.group(1).strip('"').split('.')[-1] for m in _TABLE.finditer(sql)))


def pick_database(sql: str, schemas: Dict[str, Any]) -> Optional[str]:
    """The SQL database (alias) whose tables the statement references; None when no database has them all."""
    tabs = [t.lower() for t in tables_in(sql)]
    if not tabs: return None
    best, best_hits = None, 0
    for alias, sc in schemas.items():
        names = {n.lower() for n in sc.tables}
        hits = sum(1 for t in tabs if t in names)
        if hits == len(tabs) and hits > best_hits: best, best_hits = alias, hits
    return best


def verify_run(events: Path, question: str, schemas: Dict[str, Any], llm, *, max_queries: int = 3,
               methods: Sequence[str] = ('rt', 'se', 'cohort')) -> Dict[str, Any]:
    """Verify the last `max_queries` SQL statements the agent ran that belong to one SQL database."""
    from .harness import sql_from_events
    from .sqlverify import verify_sql
    sqls = sql_from_events(events)
    picked = [(s, pick_database(s, schemas)) for s in sqls]
    picked = [(s, a) for s, a in picked if a][-max_queries:]
    checks = []
    for s, alias in picked:
        sc = schemas[alias]
        try:
            v = verify_sql(llm, question, s, sc, methods=methods, combine='and')
            checks.append({'sql': s, 'database': alias, 'accept': v['accept'], 'reasons': v['reasons'],
                           'warnings': [w for r in v['methods'].values() for w in (r.get('warnings') or r.get('differences') or [])]})
        except Exception as e:   # a verifier error is not a rejection
            checks.append({'sql': s, 'database': alias, 'accept': True, 'error': f'{type(e).__name__}: {e}'[:300], 'warnings': []})
    return {'sql_found': len(sqls), 'queries_checked': len(checks), 'any_rejected': any(not c['accept'] for c in checks),
            'checks': checks, 'usage': llm.usage.as_dict() if hasattr(llm, 'usage') else None}


def round2_prompt(original: str, previous_answer: str, result: Dict[str, Any]) -> Optional[str]:
    from .harness import continue_with_warnings
    msg = continue_with_warnings(result)
    if msg is None: return None
    prev = (previous_answer or '').strip()[-2000:] or '(no final answer was given)'
    return (original + '\n\nREVIEW OF A PREVIOUS ATTEMPT AT THIS QUESTION:\n'
            'An earlier session in this same working directory (its files are still here) gave this final answer:\n'
            + prev + '\n\n' + msg + '\nThe verifier can be wrong: if after re-checking you are confident the earlier answer is right, give it again.')
