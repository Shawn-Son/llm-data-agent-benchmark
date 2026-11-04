"""Re-run each question's unchanged validator on the recorded final answers.

Confirms that the stored grades reproduce, and lets a reviewer test a corrected answer
when checking a suspected validator false negative or false positive.
Usage: python3 -I recheck_validators.py DIGEST_DIR [DATAAGENTBENCH_CHECKOUT]
The checkout (default /home/minhyeok/dab-reproduction) provides common_scaffold, which validators
import, and the task folders whose ground_truth.csv they read via __file__. If a task folder is
missing, the ground truth stored in the digest is placed in a temporary folder instead.
"""
import glob, json, pathlib, sys, tempfile

ROOT = pathlib.Path(sys.argv[2] if len(sys.argv) > 2 else '/home/minhyeok/dab-reproduction')
sys.path.insert(0, str(ROOT))
tmp = pathlib.Path(tempfile.mkdtemp())
mismatch = total = 0
for f in sorted(glob.glob(sys.argv[1] + '/*__query*.json')):
    d = json.load(open(f))
    if not d.get('validator'): continue
    task = ROOT / f"query_{d['dataset']}" / d['query']
    if not (task / 'validate.py').exists():
        task = tmp / d['dataset'] / d['query']; task.mkdir(parents=True)
        if d.get('ground_truth') is not None: (task / 'ground_truth.csv').write_text(d['ground_truth'])
    ns = {'__file__': str(task / 'validate.py'), '__name__': 'validate'}
    exec(d['validator'], ns)
    for k, r in d['runs'].items():
        if not r or r.get('status') != 'completed' or r.get('passed') is None: continue
        got = ns['validate'](r['answer'] or '')
        got = got[0] if isinstance(got, tuple) else got
        total += 1
        if bool(got) != bool(r['passed']):
            mismatch += 1; print('MISMATCH', d['dataset'], d['query'], k, 'stored', r['passed'], 'recheck', got)
print(f'runs rechecked {total}, mismatches {mismatch}')
