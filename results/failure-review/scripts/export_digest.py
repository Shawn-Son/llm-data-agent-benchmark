"""Export compact per-question failure-analysis digests from Great Lakes run artifacts.

For every question that any of the four analysed runs got wrong (terra original,
terra run 1, Haiku runs 1-2), write one JSON with all four runs' trajectories as
ordered steps (model messages, shell commands + outputs, file edits), the run
metrics, grading, final answer, small agent-written work files, plus the task's
query, validator and ground truth. Long outputs are truncated head+tail.
Usage: python -I export_digest.py OUT_DIR
"""
import json, pathlib, sys, tarfile

HOME = pathlib.Path('/home/minhyeok')
A = HOME / 'dab-artifacts'
ROOT = HOME / 'dab-reproduction'
RUNS = {'T0': A / 'terra-native-104x1/runs', 'T1': A / 'terra-native-104x3/trial1/runs',
        'H1': A / 'haiku-claude-104x3/trial1/runs', 'H2': A / 'haiku-claude-104x3/trial2/runs'}
OUT = pathlib.Path(sys.argv[1]); OUT.mkdir(parents=True, exist_ok=True)
CMD, HEAD, TAIL, MSG, FILE = 8000, 1500, 3000, 2500, 30000


def cut(s, head=HEAD, tail=TAIL):
    s = s if isinstance(s, str) else json.dumps(s, ensure_ascii=False) if s is not None else ''
    return s if len(s) <= head + tail + 40 else s[:head] + f'\n...[{len(s) - head - tail} chars cut]...\n' + s[-tail:]


def text(c):
    if isinstance(c, str): return c
    return '\n'.join(x.get('text', '') if isinstance(x, dict) else str(x) for x in (c or []))


def steps(events):
    out, pending = [], {}
    for line in events.read_text(errors='replace').splitlines():
        try: e = json.loads(line)
        except ValueError: continue
        if not isinstance(e, dict): continue
        t = e.get('type')
        if t == 'item.completed':  # Codex
            i = e.get('item') or {}; k = i.get('type')
            if k in ('agent_message', 'reasoning'):
                out.append({'k': 'msg' if k == 'agent_message' else 'reasoning', 'text': cut(i.get('text', ''), MSG, 0)})
            elif k == 'command_execution':
                out.append({'k': 'cmd', 'cmd': cut(i.get('command', ''), CMD, 0), 'exit': i.get('exit_code'),
                            'out': cut(i.get('aggregated_output', ''))})
            elif k == 'file_change':
                out.append({'k': 'file', 'changes': cut(i.get('changes'), 4000, 0)})
            elif k:
                out.append({'k': k, 'raw': cut(i, 1500, 0)})
        elif t in ('turn.failed', 'error'):
            out.append({'k': 'error', 'raw': cut(e, 1500, 0)})
        elif t in ('assistant', 'user'):  # Claude Code
            m = e.get('message'); m = m if isinstance(m, dict) else {}
            for b in m.get('content') or []:
                if not isinstance(b, dict): continue
                if b.get('type') == 'text' and b.get('text', '').strip():
                    out.append({'k': 'msg', 'text': cut(b['text'], MSG, 0)})
                elif b.get('type') == 'tool_use':
                    s = {'k': 'tool', 'name': b.get('name'), 'input': cut(b.get('input'), CMD, 0)}
                    pending[b.get('id')] = s; out.append(s)
                elif b.get('type') == 'tool_result':
                    s = pending.pop(b.get('tool_use_id'), None)
                    r = {'out': cut(text(b.get('content'))), 'err': bool(b.get('is_error'))}
                    if s is not None: s.update(r)
                    else: out.append({'k': 'tool_result', **r})
        elif t == 'system' and e.get('subtype') == 'permission_denied':
            out.append({'k': 'denied', 'raw': cut(e, 800, 0)})
        elif t == 'result':
            out.append({'k': 'result', 'subtype': e.get('subtype'), 'turns': e.get('num_turns'), 'is_error': e.get('is_error')})
    return out


def work_files(work):
    files = {}
    if not work.is_dir(): return files
    for p in sorted(work.rglob('*')):
        rel = p.relative_to(work)
        if rel.parts[0] in ('query_dataset', 'tmp', '.claude') or p.is_symlink() or not p.is_file(): continue
        if p.suffix.lower() not in ('.py', '.sql', '.sh', '.txt', '.md', '.json', '.csv', '.js') or p.stat().st_size > FILE: continue
        if rel.name in ('db_config.yaml', 'connections.json', 'preflight_check.py'): continue
        files[str(rel)] = p.read_text(errors='replace')
    return files


def result(p):
    try: return json.loads((p / 'result.json').read_text())
    except Exception: return None


questions = set()
for d in RUNS.values():
    for p in d.glob('*/query*'):
        r = result(p)
        if r and r.get('passed') is False: questions.add((p.parent.name, p.name))

index = []
for ds, q in sorted(questions):
    task = ROOT / f'query_{ds}' / q
    doc = {'dataset': ds, 'query': q,
           'question': (task / 'query.json').read_text(errors='replace') if (task / 'query.json').exists() else None,
           'validator': (task / 'validate.py').read_text(errors='replace') if (task / 'validate.py').exists() else None,
           'ground_truth': (task / 'ground_truth.csv').read_text(errors='replace')[:20000] if (task / 'ground_truth.csv').exists() else None,
           'runs': {}}
    for k, d in RUNS.items():
        p = d / ds / q; r = result(p)
        if r is None: doc['runs'][k] = None; continue
        g = json.loads((p / 'grading.json').read_text()) if (p / 'grading.json').exists() else {}
        doc['runs'][k] = {'status': r.get('status'), 'passed': r.get('passed'), 'grader_reason': g.get('reason'),
                          'answer': r.get('answer'), 'metrics': {m: r.get(m) for m in ('duration_s', 'tool_calls', 'command_calls', 'command_errors',
                                                                                     'input_tokens', 'output_tokens', 'num_turns', 'terminal_subtype')},
                          'steps': steps(p / 'events.jsonl') if (p / 'events.jsonl').exists() else [],
                          'work_files': work_files(p / 'work')}
    (OUT / f'{ds}__{q}.json').write_text(json.dumps(doc, ensure_ascii=False, indent=1))
    index.append({'dataset': ds, 'query': q, **{k: (v or {}).get('passed') for k, v in doc['runs'].items()}})

descs = {}
for ds in sorted({d for d, _ in questions}):
    f = ROOT / f'query_{ds}' / 'db_description_withhint.txt'
    descs[ds] = (ROOT / f'query_{ds}' / 'db_description.txt').read_text(errors='replace') + '\n\n' + (f.read_text(errors='replace') if f.exists() else '')
(OUT / '_datasets.json').write_text(json.dumps(descs, ensure_ascii=False, indent=1))
(OUT / '_index.json').write_text(json.dumps(index, indent=1))

keys = [k.read_bytes().strip() for k in [HOME / '.config/dab/key', HOME / '.config/dab/anthropic_key'] if k.exists()]
hits = [f.name for f in OUT.glob('*.json') if any(k in f.read_bytes() for k in keys)]
assert not hits, f'credential found in {hits}'
size = sum(f.stat().st_size for f in OUT.glob('*.json'))
print(f'DIGEST_OK questions={len(questions)} files={len(list(OUT.glob("*.json")))} bytes={size} keys_checked={len(keys)}')
