"""Collect the method-condition results on Great Lakes into one small bundle for the repository.

    strict/.venv/bin/python experiments/collect_method_results.py OUT_DIR

OUT_DIR/results/haiku-claude-<method>-104x3/trial1/   finalize104 reports (without archive-manifest.json;
                                                        ARCHIVE.json keeps the archive path and checksum)
OUT_DIR/results/haiku-claude-sqlverify-104x3/trial1/verify_details.json   every question's SQL selection and verdicts
OUT_DIR/results/method-prep/<method>/                  per-dataset MANIFEST, README, spec statistics (no tracebacks),
                                                        summary.json with the LLM cost of every preprocessing run
Preprocessing CSVs and full trajectories stay on scratch ($DAB_SCRATCH/dab-prep, dab-artifacts, dab-archives).
"""
import json, os, shutil, sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
SCRATCH = Path(os.environ.get('DAB_SCRATCH', '/scratch/cse584f26_class_root/cse584f26_class/minhyeok'))
METHODS = ('fdj', 'docetl', 'sqlverify')


def main(out):
    out = Path(out); (out / 'results').mkdir(parents=True, exist_ok=True)
    for m in METHODS:
        src = PROJECT / 'results' / f'haiku-claude-{m}-104x3' / 'trial1'
        dst = out / 'results' / src.parent.name / 'trial1'
        if not src.exists(): print('missing', src); continue
        shutil.copytree(src, dst, dirs_exist_ok=True, ignore=shutil.ignore_patterns('archive-manifest.json'))
    runs = SCRATCH / 'dab-artifacts' / 'haiku-claude-sqlverify-104x3' / 'trial1' / 'runs'
    details = []
    for v in sorted(runs.glob('*/query*/verify.json')):
        q = v.parent; r = json.loads((q / 'result.json').read_text())
        d = json.loads(v.read_text()); d.pop('usage', None)
        details.append({'dataset': q.parent.name, 'query': int(q.name[5:]), 'round1_passed': r.get('round1_passed'),
                        'round2_ran': r.get('round2_ran'), 'round2_passed': r.get('round2_passed'), 'passed': r.get('passed'), **d})
    if details:
        (out / 'results' / 'haiku-claude-sqlverify-104x3' / 'trial1' / 'verify_details.json').write_text(json.dumps(details, indent=1, default=str) + '\n')
    for m in ('fdj', 'docetl'):
        src = SCRATCH / 'dab-prep' / m; dst = out / 'results' / 'method-prep' / m
        if not src.exists(): continue
        dst.mkdir(parents=True, exist_ok=True)
        runs_ = []
        for f in sorted(src.glob('run-*.json')):
            s = json.loads(f.read_text())
            runs_.append({'file': f.name, 'cost_usd': (s.get('usage') or {}).get('cost_usd'), 'calls': (s.get('usage') or {}).get('calls'),
                          'statuses': {k: v.get('status') for k, v in s.get('specs', {}).items()}})
        specs = {}
        for ds in sorted(p for p in src.iterdir() if p.is_dir()):
            (dst / ds.name).mkdir(exist_ok=True)
            for n in ('MANIFEST.json', 'README.md'):
                if (ds / n).exists(): shutil.copyfile(ds / n, dst / ds.name / n)
            for f in ds.glob('*.json'):
                if f.name == 'MANIFEST.json': continue
                info = json.loads(f.read_text()); info.pop('trace', None)
                (dst / ds.name / f.name).write_text(json.dumps(info, indent=1, default=str) + '\n')
                specs[f'{ds.name}/{f.stem}'] = {k: info.get(k) for k in ('status', 'matches', 'left_size', 'right_size', 'rows', 'refined',
                                                                          'clusters', 'left_matched', 'error', 'seconds')}
                if m == 'docetl': specs[f'{ds.name}/{f.stem}']['fields'] = {k: {x: v.get(x) for x in ('status', 'code_coverage', 'llm_rows', 'error')} | {'final_coverage': (v.get('summary') or {}).get('final_coverage')} for k, v in (info.get('fields') or {}).items()}
        summary = {'cost_usd': sum(r['cost_usd'] or 0 for r in runs_), 'runs': runs_, 'specs': specs,
                   'note': 'cost_usd sums the dabcheck LLM estimate of every preprocessing run (cached calls are free); CSV outputs stay on scratch'}
        (dst / 'summary.json').write_text(json.dumps(summary, indent=1, default=str) + '\n')
    print('collected into', out)


COMPACT = ('method_runs.csv', 'aggregate_metrics.json', 'protocol.json', 'datasets.csv', 'report.md', 'verifier_cost.json', 'ARCHIVE.json')


def compact(full, out):
    """The small subset committed from a session without push access to Great Lakes: per-question
    method fields, metrics, protocol, prep summaries, and the verdicts of the SQL that was verified."""
    full, out = Path(full), Path(out); bundle = {}
    for m in METHODS:
        d = full / 'results' / f'haiku-claude-{m}-104x3' / 'trial1'
        for n in COMPACT:
            if (d / n).exists(): bundle[f'results/haiku-claude-{m}-104x3/trial1/{n}'] = (d / n).read_text()
    vd = full / 'results' / 'haiku-claude-sqlverify-104x3' / 'trial1' / 'verify_details.json'
    if vd.exists():
        rows = json.loads(vd.read_text())
        checked = [{'dataset': r['dataset'], 'query': r['query'], 'round1_passed': r['round1_passed'], 'round2_passed': r['round2_passed'],
                    'checks': [{'database': c.get('database'), 'accept': c.get('accept'), 'sql': (c.get('sql') or '')[:500],
                                'reasons': [x[:300] for x in c.get('reasons') or []]} for c in r.get('checks') or []]}
                   for r in rows if r.get('queries_checked')]
        counts = {'questions': len(rows), 'with_single_database_sql': sum(1 for r in rows if r.get('candidates')),
                  'with_answer_level_sql': len(checked), 'rejected': sum(1 for r in rows if r.get('any_rejected'))}
        bundle['results/haiku-claude-sqlverify-104x3/trial1/verify_summary.json'] = json.dumps({'counts': counts, 'checked': checked}, indent=1) + '\n'
    for f in sorted((full / 'results' / 'method-prep').rglob('*')):
        if f.is_file() and (f.name in ('summary.json', 'MANIFEST.json', 'README.md')):
            bundle[str(f.relative_to(full))] = f.read_text()
    out.write_text(json.dumps(bundle))
    print('compact bundle', out, len(bundle), 'files', out.stat().st_size, 'bytes')


if __name__ == '__main__':
    main(sys.argv[1])
    if len(sys.argv) > 2: compact(sys.argv[1], sys.argv[2])
