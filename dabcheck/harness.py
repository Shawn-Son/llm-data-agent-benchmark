"""Harness-side use of dabcheck (observe -> detect -> respond).

- `prompt_addendum()`      : the agent-facing instructions appended to the task prompt under the
                             "description+hints+checks" condition (code-only checks; the agent sandbox has no network).
- `stage_package(work)`    : copy the package into the agent's working directory.
- `sql_from_events(path)`  : SQL statements the agent ran, recovered from Codex / Claude Code event logs.
- `post_run_verify(...)`   : run the LLM-backed verifiers (round trip, synthetic execution, cohort cards) on the
                             SQL of a finished run, outside the sandbox, and write checks.json with warnings.
  A second agent round that receives these warnings is the "respond" step; it is left to the caller
  (`continue_with_warnings` shows the prompt it should get).
"""
from __future__ import annotations
import json, re, shutil
from pathlib import Path
from typing import Any, Dict, List, Optional

PACKAGE_DIR = Path(__file__).resolve().parent
CONDITION = 'description+hints+checks'
_SQL = re.compile(r'(?is)\b((?:WITH\b.*?\bSELECT|SELECT)\b.*?)(?:;|"|\n|$)')


def prompt_addendum() -> str:
    return (PACKAGE_DIR / 'AGENT_INSTRUCTIONS.md').read_text().strip()


def stage_package(work: Path) -> Path:
    dest = Path(work) / 'dabcheck'
    if dest.exists(): shutil.rmtree(dest)
    shutil.copytree(PACKAGE_DIR, dest, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    return dest


def _texts_from_events(path: Path) -> List[str]:
    out = []
    for line in Path(path).read_text(errors='replace').splitlines():
        try: e = json.loads(line)
        except ValueError: continue
        if not isinstance(e, dict): continue
        item = e.get('item') or {}
        if e.get('type') == 'item.completed' and item.get('type') == 'command_execution':   # Codex
            out.append(str(item.get('command', '')))
        if e.get('type') == 'item.completed' and item.get('type') == 'file_change':
            for ch in item.get('changes') or []: out.append(str(ch.get('diff', '')))
        m = e.get('message')
        for b in (m.get('content') if isinstance(m, dict) else None) or []:                   # Claude Code
            if isinstance(b, dict) and b.get('type') == 'tool_use':
                inp = b.get('input') or {}
                for k in ('command', 'content', 'new_string'):
                    if isinstance(inp.get(k), str): out.append(inp[k])
    return out


def sql_from_events(path: Path, min_len: int = 30) -> List[str]:
    """Distinct SELECT statements found in the agent's commands and written files (heuristic)."""
    seen, out = set(), []
    for text in _texts_from_events(path):
        text = text.replace('\\n', '\n')
        for m in _SQL.finditer(text):
            s = re.sub(r'\s+', ' ', m.group(1)).strip().rstrip(';').rstrip('\\')
            if len(s) >= min_len and s.lower() not in seen and ' from ' in s.lower():
                seen.add(s.lower()); out.append(s)
    return out


def post_run_verify(folder: Path, question: str, schema, llm, *, methods=('rt', 'cohort', 'se'), max_queries: int = 5,
                    combine: str = 'and') -> Dict[str, Any]:
    """Verify the last `max_queries` SQL statements of a run; write <folder>/checks.json."""
    from .sqlverify import verify_sql
    folder = Path(folder)
    sqls = sql_from_events(folder / 'events.jsonl')[-max_queries:]
    checks = []
    for s in sqls:
        v = verify_sql(llm, question, s, schema, methods=methods, combine=combine)
        checks.append({'sql': s, 'accept': v['accept'], 'reasons': v['reasons'],
                       'warnings': [w for r in v['methods'].values() for w in (r.get('warnings') or r.get('differences') or [])]})
    result = {'condition': CONDITION, 'queries_checked': len(checks), 'any_rejected': any(not c['accept'] for c in checks), 'checks': checks,
              'usage': llm.usage.as_dict() if hasattr(llm, 'usage') else None}
    (folder / 'checks.json').write_text(json.dumps(result, indent=2, default=str) + '\n')
    return result


def continue_with_warnings(result: Dict[str, Any]) -> Optional[str]:
    """The message a second agent round receives (the "respond" step); None when nothing was rejected."""
    rejected = [c for c in result.get('checks', []) if not c['accept']]
    if not rejected: return None
    lines = ['A verifier reviewed the SQL you ran and found that it may not implement the question:']
    for c in rejected:
        lines.append('- SQL: ' + c['sql'][:300])
        for w in c['warnings'][:4]: lines.append('    warning: ' + str(w)[:300])
    lines.append('Re-check these points against the question (date column, time window, population, denominator) and, '
                 'if needed, recompute. Then give the final answer again, alone on its own line.')
    return '\n'.join(lines)
