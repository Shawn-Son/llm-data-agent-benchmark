"""Trace-level analysis of the method conditions (run on Great Lakes, where the trajectories are).

    strict/.venv/bin/python experiments/analyze_method_traces.py OUT.json OUT.md

For every question where a method acted (outputs staged, or a second round ran) and every question whose
outcome differs from both baseline trials, it records: whether the agent opened the method outputs, what the
final answer says about them, the official grader reason in the condition and in both baseline trials, and
(sqlverify) both rounds. It also checks that untouched questions got the baseline prompt byte for byte, and
measures the delivered FDJ / DocETL outputs (candidates per key, cluster sizes, extraction sources).
Grader reasons are the same strings the baseline failure_analysis.csv already publishes.
"""
import csv, hashlib, json, os, re, sys
from collections import Counter
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
SCRATCH = Path(os.environ.get('DAB_SCRATCH', '/scratch/cse584f26_class_root/cse584f26_class/minhyeok'))
NEW = SCRATCH / 'dab-artifacts'
BASE = Path('/home/minhyeok/dab-artifacts/haiku-claude-104x3')
PREP = SCRATCH / 'dab-prep'
METHODS = ('fdj', 'docetl', 'sqlverify')
MENTION = re.compile(r'[^.\n]*(?:dabcheck_prep|precomputed|pre-computed|DocETL|FDJ|docetl_|fdj_)[^.\n]*', re.I)


def short(s, n=220): s = re.sub(r'\s+', ' ', str(s or '')).strip(); return s if len(s) <= n else s[:n] + '...'


def read(p):
    try: return Path(p).read_text(errors='replace')
    except OSError: return ''


def grade(folder, name='grading.json'):
    try: g = json.loads(read(Path(folder) / name)); return {'passed': g.get('passed'), 'reason': short(g.get('reason'), 200)}
    except ValueError: return None


def tool_uses(events):
    out = []
    for line in read(events).splitlines():
        try: e = json.loads(line)
        except ValueError: continue
        m = e.get('message') if isinstance(e, dict) else None
        for b in (m.get('content') if isinstance(m, dict) else None) or []:
            if isinstance(b, dict) and b.get('type') == 'tool_use': out.append((b.get('name'), json.dumps(b.get('input'))))
    return out


def prep_usage(events):
    uses = tool_uses(events)
    hits = [i for i, (_, inp) in enumerate(uses) if 'dabcheck_prep' in inp or re.search(r'(docetl|fdj)_\w+\.csv', inp)]
    loads = [i for i in hits if re.search(r'read_csv|csv\.|open\(|pd\.read|duckdb|sqlite', uses[i][1])]
    return {'tool_calls': len(uses), 'calls_touching_prep': len(hits), 'calls_loading_prep_csv': len(loads),
            'first_prep_call': hits[0] if hits else None, 'read_readme': any('README.md' in uses[i][1] for i in hits)}


def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest() if Path(p).exists() else None


def main(out_json, out_md):
    base = [{} for _ in (1, 2)]
    for t in (1, 2):
        for f in (BASE / f'trial{t}' / 'runs').glob('*/query*'):
            base[t - 1][(f.parent.name, int(f.name[5:]))] = f
    report = {'questions': {}, 'prompt_identity': {}, 'prep_outputs': {}}
    md = ['# Trace-level analysis of the method conditions', '']
    for m in METHODS:
        runs = NEW / f'haiku-claude-{m}-104x3' / 'trial1' / 'runs'
        rows = {}
        for f in sorted(runs.glob('*/query*')):
            k = (f.parent.name, int(f.name[5:])); r = json.loads(read(f / 'result.json') or '{}')
            b = [grade(base[i][k]) if k in base[i] else None for i in (0, 1)]
            acted = bool(r.get('round2_ran')) if m == 'sqlverify' else bool(r.get('method_inputs_staged'))
            changed = all(x is not None and x['passed'] != r.get('passed') for x in b)
            same_prompt = sha(f / 'prompt.txt') == sha(base[0][k] / 'prompt.txt') if k in base[0] else None
            report['prompt_identity'].setdefault(m, Counter())[f"{'acted' if acted else 'untouched'}:{'same' if same_prompt else 'different'}"] += 1
            if not (acted or changed): continue
            ans = read(f / 'work' / 'answer.txt')
            q = {'method': m, 'acted': acted, 'changed_vs_both_baselines': changed, 'passed': r.get('passed'),
                 'grade': grade(f), 'baseline_grades': b, 'answer_tail': short(ans[-400:], 300),
                 'answer_mentions_method': [short(x, 200) for x in MENTION.findall(ans)][:3]}
            if m in ('fdj', 'docetl') and acted: q['prep_usage'] = prep_usage(f / 'events.jsonl')
            if m == 'sqlverify' and acted:
                q['round1'] = {'grade': grade(f, 'grading_round1.json'), 'answer_tail': short(read(f / 'answer_round1.txt')[-300:], 200)}
                q['warnings_sent'] = [short(x, 200) for x in re.findall(r'warning: (.*)', read(f / 'prompt_round2.txt'))][:4]
            rows[f'{k[0]} q{k[1]}'] = q
        report['questions'][m] = rows
    # delivered method outputs
    def csv_rows(p):
        with open(p, newline='') as f: return list(csv.DictReader(f))
    po = {}
    for f in sorted((PREP / 'fdj').glob('*/fdj_*.csv')):
        rr = csv_rows(f)
        if 'cluster_id' in (rr[0] if rr else {}):
            sizes = Counter(Counter(r['cluster_id'] for r in rr).values())
            po[f'fdj/{f.parent.name}/{f.name}'] = {'records': len(rr), 'clusters': sum(sizes.values()), 'cluster_size_histogram': dict(sorted(sizes.items())[:12])}
            if f.parent.name == 'civic_unstructured':
                groups = {}
                for r in rr: groups.setdefault(r['cluster_id'], []).append(r[[c for c in r if c != 'cluster_id'][0]])
                po[f'fdj/{f.parent.name}/{f.name}']['multi_name_clusters'] = [sorted(g) for g in groups.values() if len(g) > 1][:40]
        else:
            per_left = Counter(r['left_value'] for r in rr); per_right = Counter(r['right_value'] for r in rr)
            po[f'fdj/{f.parent.name}/{f.name}'] = {'pairs': len(rr), 'left_values': len(per_left), 'right_values': len(per_right),
                                                    'candidates_per_left_histogram': dict(sorted(Counter(per_left.values()).items())[:15]),
                                                    'left_with_exactly_one': sum(1 for v in per_left.values() if v == 1),
                                                    'sample_pairs': [[r['left_value'], r['right_value']] for r in rr[:5]]}
    for f in sorted((PREP / 'docetl').glob('*/docetl_*.csv')):
        rr = csv_rows(f); cols = [c for c in (rr[0] if rr else {}) if c.endswith('_source')]
        d = {'rows': len(rr)}
        for c in cols:
            d[c] = dict(Counter(r[c] or 'none' for r in rr))
        if f.name == 'docetl_award_amounts.csv':
            text_col = 'amount_text'
            d['sample_unparsed_texts'] = [short(r[text_col], 160) for r in rr if not r.get('amount_usd_source')][:6]
            d['sample_llm_values'] = [[short(r[text_col], 120), r['amount_usd']] for r in rr if r.get('amount_usd_source') == 'llm'][:6]
        po[f'docetl/{f.parent.name}/{f.name}'] = d
    report['prep_outputs'] = po
    report['prompt_identity'] = {m: dict(v) for m, v in report['prompt_identity'].items()}
    Path(out_json).write_text(json.dumps(report, indent=1, default=str) + '\n')
    # markdown digest
    md += ['## Prompt identity with the baseline (prompt.txt sha256, baseline trial 1)', '']
    md += [f'- {m}: {v}' for m, v in report['prompt_identity'].items()]
    for m in METHODS:
        md += ['', f'## {m}', '', '| Question | Acted | Result (cond / base t1 / t2) | Agent use of outputs | Condition grader reason | Answer says |', '|---|---|---|---|---|---|']
        for k, q in report['questions'][m].items():
            b = q['baseline_grades']; res = f"{q['passed']} / {b[0]['passed'] if b[0] else '-'} / {b[1]['passed'] if b[1] else '-'}"
            use = q.get('prep_usage'); use = f"{use['calls_touching_prep']} calls, {use['calls_loading_prep_csv']} loads, README {use['read_readme']}" if use else ''
            if m == 'sqlverify' and q['acted']: use = f"round 1 {q['round1']['grade']['passed'] if q['round1']['grade'] else '-'} -> round 2 {q['passed']}"
            md.append(f"| {k} | {q['acted']} | {res} | {use} | {(q['grade'] or {}).get('reason', '')} | {'; '.join(q['answer_mentions_method'])[:200]} |")
    md += ['', '## Delivered method outputs', '']
    for k, v in po.items(): md.append(f'- `{k}`: ' + json.dumps({a: b for a, b in v.items() if a not in ('sample_pairs', 'multi_name_clusters', 'sample_unparsed_texts', 'sample_llm_values')}))
    Path(out_md).write_text('\n'.join(md) + '\n')
    print('wrote', out_json, out_md)


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2])
