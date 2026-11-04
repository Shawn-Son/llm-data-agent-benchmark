"""Process signals per scored run (section 6 of FAILURE_REVIEW.md).

Reads the digests written by export_digest.py and writes one record per scored run:
tool calls, failing commands, longest failing streak, /tmp-file losses, timeouts,
hedged/declined answer language, duration. Prints the wrong/right summary per model.
Usage: python3 -I signals.py DIGEST_DIR [OUT_JSON]   (default OUT_JSON: signals.json)
"""
import json, glob, re, statistics as st, sys

D = sys.argv[1]
OUT = sys.argv[2] if len(sys.argv) > 2 else 'signals.json'
HEDGE = re.compile(r"\b(lower bound|estimate|approximate|low[- ]confidence|best[- ]effort|could not|can't give|cannot give|couldn't|not (?:a )?verified|heuristic)\b", re.I)
DECL = re.compile(r"(I could not (?:determine|produce)|I can't give you (?:a|an exact)|not giving a number|I'm not naming|can't give an exact)", re.I)


def bad(x):
    return (x['k'] == 'cmd' and x.get('exit') not in (0, None)) or (x['k'] == 'tool' and x.get('err'))


rows = []
for f in sorted(glob.glob(D + '/*__query*.json')):
    d = json.load(open(f))
    for k, r in d['runs'].items():
        if not r or r['status'] != 'completed' or r['passed'] is None: continue  # unscored runs are never counted
        s = r['steps']; model = 'terra' if k.startswith('T') else 'haiku'
        cmds = [x for x in s if x['k'] in ('cmd', 'tool')]
        fails = [x for x in cmds if bad(x)]
        outs = ' '.join(str(x.get('out', '')) for x in cmds)
        tmp = len(re.findall(r"No such file or directory: '?/tmp/|/tmp/\S+: No such file|can't open file '/tmp/", outs))
        tout = len(re.findall(r"timed out after|Exit code 143", outs))
        ans = r['answer'] or ''
        best = cur = 0  # longest run of consecutive failing commands
        for x in cmds:
            cur = cur + 1 if bad(x) else 0; best = max(best, cur)
        rows.append(dict(model=model, run=k, q=f"{d['dataset']}:{d['query']}", passed=r['passed'], steps=len(s), tools=len(cmds), fails=len(fails),
                         fail_rate=len(fails) / max(1, len(cmds)), streak=best, tmp=tmp, timeout=tout, hedged=bool(HEDGE.search(ans)),
                         declined=bool(DECL.search(ans)), dur=r['metrics'].get('duration_s') or 0, ans_len=len(ans)))
json.dump(rows, open(OUT, 'w'))


def summ(rs):
    return dict(n=len(rs), med_tools=st.median(r['tools'] for r in rs), med_fail=st.median(r['fails'] for r in rs),
                fail_rate=round(st.mean(r['fail_rate'] for r in rs), 3), streak3=sum(r['streak'] >= 3 for r in rs),
                tmp_runs=sum(r['tmp'] > 0 for r in rs), timeout_runs=sum(r['timeout'] > 0 for r in rs),
                hedged=sum(r['hedged'] for r in rs), declined=sum(r['declined'] for r in rs), med_dur=round(st.median(r['dur'] for r in rs)))


for m in ['terra', 'haiku']:
    for p in [False, True]:
        rs = [r for r in rows if r['model'] == m and r['passed'] == p]
        print(m, 'right' if p else 'wrong', summ(rs))
