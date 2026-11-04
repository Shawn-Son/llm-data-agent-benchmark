"""Combine the per-question review findings ([A-F]_*.json).

1. Per model, over all wrong runs: primary categories, sub-issues, evidence levels, signals
   (sections 1-4 of FAILURE_REVIEW.md).
2. Questions a model got wrong in both of its runs (terra T0+T1, Haiku H1+H2), one primary
   category per question (section 7): the category both runs share; if the runs disagree,
   the category of the run with the stronger evidence (supported > likely > unresolved),
   and the first run on a tie. Written to both_runs_wrong.csv.
Usage: python3 -I synth.py [FINDINGS_DIR]   (default: the folder above this script)
"""
import collections, csv, glob, json, pathlib, sys

DIR = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else pathlib.Path(__file__).resolve().parent.parent
F = sorted(DIR.glob('[A-F]_*.json'))
items = [x for f in F for x in json.load(open(f))]
print('files', len(F), 'questions', len(items))
M = {'terra': ('T0', 'T1'), 'haiku': ('H1', 'H2')}

cnt, prim, sig, ev = ({m: collections.Counter() for m in M} for _ in range(4))
nfail = {m: 0 for m in M}
for it in items:
    for k, r in (it.get('runs') or {}).items():
        if not isinstance(r, dict) or r.get('passed') is not False: continue
        m = 'terra' if k.startswith('T') else 'haiku'; nfail[m] += 1
        prim[m][r.get('primary')] += 1; ev[m][r.get('evidence')] += 1
        for s in r.get('sub_issues') or []: cnt[m][s.split()[0][:3]] += 1
        for s in r.get('signals') or []: sig[m][s] += 1
for m in M:
    print('\n==', m, 'wrong runs', nfail[m]); print(' primary', prim[m].most_common()); print(' sub', cnt[m].most_common(14))
    print(' evidence', dict(ev[m])); print(' signals', sig[m].most_common())

RANK = {'supported': 2, 'likely': 1, 'unresolved': 0}
out = []
for m, (a, b) in M.items():
    for it in items:
        r = it.get('runs') or {}
        x, y = r.get(a) or {}, r.get(b) or {}
        if x.get('passed') is not False or y.get('passed') is not False: continue
        if x['primary'] == y['primary']: c, rule = x['primary'], 'same'
        else: c, rule = (x if RANK.get(x['evidence'], 0) >= RANK.get(y['evidence'], 0) else y)['primary'], 'split: stronger evidence'
        out.append({'model': m, 'dataset': it['dataset'], 'query': it['query'], 'primary': c, 'rule': rule,
                    f'run_a': a, 'run_a_primary': x['primary'], 'run_a_evidence': x['evidence'],
                    'run_b': b, 'run_b_primary': y['primary'], 'run_b_evidence': y['evidence']})
out.sort(key=lambda o: (o['model'] != 'terra', o['primary'], o['dataset'], int(o['query'][5:])))
with open(DIR / 'both_runs_wrong.csv', 'w', newline='') as f:
    w = csv.DictWriter(f, fieldnames=list(out[0])); w.writeheader(); w.writerows(out)
for m in M:
    rs = [o for o in out if o['model'] == m]
    print(f'\n== {m}: {len(rs)} questions wrong in both runs ({sum(o["rule"] == "same" for o in rs)} with the same category in both)')
    for c, n in collections.Counter(o['primary'] for o in rs).most_common(): print(f'  {c}: {n}')
