from __future__ import annotations
import hashlib, json, math, os, re, subprocess
from pathlib import Path

UPSTREAM = '61fb21e0766d775acae443f6074f5d498e95f938'

def digest(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1024*1024), b''): h.update(chunk)
    return h.hexdigest()

def write_json(path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n')
    temp.replace(path)

def queries(root):
    return [(p.parent.parent.name.removeprefix('query_'), int(p.parent.name[5:]), p)
            for p in sorted(Path(root).glob('query_*/query[0-9]*/query.json'))
            if re.fullmatch(r'query\d+', p.parent.name)]

def pass_k(n, c, k):
    if not 1 <= k <= n: return None
    return 1.0 if n-c < k else 1 - math.comb(n-c, k)/math.comb(n, k)

def trace_stats(path):
    stats = dict(tool_calls=0, command_calls=0, command_failures=0, turns=0,
                 input_tokens=0, cached_input_tokens=0, output_tokens=0,
                 api_errors=0, malformed_events=0)
    items, commands, usage_seen = {}, [], False
    if not Path(path).exists(): return stats | {'usage_available': False}, commands
    for line in Path(path).read_text(errors='replace').splitlines():
        try: event = json.loads(line)
        except ValueError: stats['malformed_events'] += 1; continue
        if event.get('type') == 'turn.completed':
            stats['turns'] += 1
            usage = event.get('usage', {}); usage_seen |= bool(usage)
            for key in ('input_tokens','cached_input_tokens','output_tokens'):
                stats[key] += usage.get(key, 0) or 0
        if event.get('type') in ('error','turn.failed'): stats['api_errors'] += 1
        if event.get('type') == 'item.completed':
            item = event.get('item', {})
            items[item.get('id', str(len(items)))] = item
    for item in items.values():
        kind = item.get('type')
        if kind in ('command_execution','mcp_tool_call','file_change','web_search'):
            stats['tool_calls'] += 1
        if kind == 'command_execution':
            stats['command_calls'] += 1
            stats['command_failures'] += item.get('exit_code') not in (None, 0)
            commands.append(item)
    return stats | {'usage_available': usage_seen}, commands

def validate(root, dataset, query, answer, out):
    # Official graders execute OUTSIDE the agent container, after inference.
    script = '''import importlib.util,json,sys
from pathlib import Path
p=Path(sys.argv[1]);sys.path.insert(0,sys.argv[2])
s=importlib.util.spec_from_file_location("dab_validator",p)
m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
r=m.validate(Path(sys.argv[3]).read_text())
if isinstance(r,tuple): ok,reason=r
else: ok,reason=r,""
print(json.dumps({"passed":bool(ok),"reason":str(reason)}))
'''
    validator = Path(root)/f'query_{dataset}'/f'query{query}'/'validate.py'
    try:
        p = subprocess.run([os.sys.executable,'-c',script,str(validator),str(Path(root).resolve()),str(Path(answer).resolve())],
                           cwd=validator.parent, capture_output=True,text=True,timeout=60)
        if p.returncode: raise RuntimeError(p.stderr[-4000:])
        result = json.loads(p.stdout.splitlines()[-1])
        result.update(status='scored', validator_sha256=digest(validator))
    except Exception as exc:
        result = dict(status='grader_error', passed=None, reason=str(exc))
    write_json(out, result)
    return result
