"""Compare the three method conditions with the Haiku baseline (same 104 questions; every trial found is used).

    python experiments/compare_methods.py            # reads results/, writes results/method-comparison/

Inputs (all in the repository after finalize104.py):
  results/haiku-claude-104x3/trial{1,2}/runs.csv                baseline
  results/haiku-claude-<method>-104x3/trial{1,2}/runs.csv        method condition (+ method_runs.csv)
  results/failure-review/both_runs_wrong.csv                     review category of every Haiku both-runs-wrong question
"""
from __future__ import annotations
import csv, json, statistics
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RES = ROOT / 'results'
OUT = RES / 'method-comparison'
METHODS = {'fdj': 'Identifier joins and identity', 'docetl': 'Extraction and representation', 'sqlverify': 'Cohort / temporal'}
TARGET = {'fdj': {'Identifier joins and identity'}, 'docetl': {'Extraction and representation'},
          'sqlverify': {'Cohort and aggregation', 'Temporal state and status'}}


def load(tag, trial, name='runs.csv'):
    p = RES / tag / f'trial{trial}' / name
    if not p.exists(): return None
    return {(r['dataset'], int(r['query'])): r for r in csv.DictReader(p.open())}


def passed(r):
    v = r.get('passed') if r else None
    return True if v == 'True' else False if v == 'False' else None


def cost(rows): return sum(float(r.get('estimated_cost_usd') or 0) for r in rows.values())


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    base = [load('haiku-claude-104x3', t) for t in (1, 2)]
    cats = {}
    for r in csv.DictReader((RES / 'failure-review' / 'both_runs_wrong.csv').open()):
        if r['model'] == 'haiku': cats[(r['dataset'], int(r['query'].replace('query', '')))] = r['primary']
    keys = sorted(base[0])
    md = ['# Method conditions vs the Haiku baseline (104 questions, 2 trials each)', '',
          'Same questions, prompts, sandbox and original validators; Haiku as the agent and as every LLM inside the methods.',
          'Accuracy = correct / scored per trial. "Fixed" = a question Haiku got wrong in both baseline trials that the',
          'condition got right in at least one of its trials; "Lost" = right in both baseline trials, wrong in every condition trial.',
          'Pass@k uses the condition\'s own number of trials (k = 2 for the baseline, 1 for a single-trial condition).', '',
          '| Condition | Trials | Accuracy per trial (scored) | Mean | Pass@k | Fixed (target category) | Fixed (other) | Lost | Agent cost (USD, all trials) |',
          '|---|---|---|---|---|---|---|---|---|']
    summary = {}

    def row(label, trials, target=None):
        accs, scored = [], []
        for t in trials:
            sc = [k for k in keys if passed(t.get(k)) is not None]
            accs.append(sum(passed(t[k]) for k in sc) / len(sc)); scored.append(len(sc))
        both = [k for k in keys if all(passed(t.get(k)) is not None for t in trials)]
        p2 = sum(any(passed(t[k]) for t in trials) for k in both) / len(both)
        bw = [k for k in keys if all(passed(b.get(k)) is False for b in base)]
        fixed = [k for k in bw if any(passed(t.get(k)) for t in trials)]
        lost = [k for k in keys if all(passed(b.get(k)) for b in base) and all(passed(t.get(k)) is False for t in trials)]
        ft = [k for k in fixed if target and cats.get(k) in target]
        fo = [k for k in fixed if k not in ft]
        c = sum(cost(t) for t in trials)
        per = ' / '.join(f'{x:.1%} ({n})' for x, n in zip(accs, scored))
        md.append(f"| {label} | {len(trials)} | {per} | {statistics.mean(accs):.1%} | {p2:.1%} | "
                  f"{len(ft)}{' ' + ', '.join(f'{d} q{q}' for d, q in ft) if ft else ''} | {len(fo)}{' ' + ', '.join(f'{d} q{q}' for d, q in fo) if fo else ''} | "
                  f"{len(lost)}{' ' + ', '.join(f'{d} q{q}' for d, q in lost) if lost else ''} | {c:.2f} |")
        return {'accuracy': accs, 'scored': scored, 'pass_at_2': p2, 'fixed_target': ft, 'fixed_other': fo, 'lost': lost, 'agent_cost_usd': c}
    summary['baseline'] = row('Haiku baseline', base)
    for m in METHODS:
        trials = [x for x in (load(f'haiku-claude-{m}-104x3', t) for t in (1, 2)) if x]
        if not trials: md.append(f'| {m} | 0 | (missing) | | | | | | |'); continue
        summary[m] = row(f'{m} ({METHODS[m]})', trials, TARGET[m])
    # per review category: questions Haiku got wrong in both baseline trials, and how many each condition fixed
    md += ['', '## Haiku both-runs-wrong questions by review category', '',
           '| Category | Questions | ' + ' | '.join(f'{m} fixed' for m in METHODS) + ' |', '|---|---|' + '---|' * len(METHODS)]
    by_cat = defaultdict(list)
    for k, c in cats.items(): by_cat[c].append(k)
    for c, ks in sorted(by_cat.items()):
        cells = []
        for m in METHODS:
            s = summary.get(m)
            cells.append(str(sum(1 for k in ks if s and (k in s['fixed_target'] or k in s['fixed_other']))) if s else '-')
        md.append(f'| {c} | {len(ks)} | ' + ' | '.join(cells) + ' |')
    # sqlverify: verifier verdicts against round-1 correctness, and what the second round changed
    mv = [x for x in (load('haiku-claude-sqlverify-104x3', t, 'method_runs.csv') for t in (1, 2)) if x]
    if mv:
        cnt = defaultdict(int)
        for t in mv:
            for r in t.values():
                if r['round1_passed'] in ('', 'None'): continue
                r1 = r['round1_passed'] == 'True'; checked = int(r['verify_checked'] or 0) > 0
                if not checked: cnt['no_sql_checked'] += 1; continue
                rej = r['verify_rejected'] == 'True'
                cnt[('reject' if rej else 'accept') + ('_right' if r1 else '_wrong')] += 1
                if r['round2_ran'] == 'True':
                    r2 = r['round2_passed'] == 'True'
                    cnt[f'round2_{"right" if r1 else "wrong"}_to_{"right" if r2 else "wrong"}'] += 1
        acc_r1 = [sum(1 for r in t.values() if r['round1_passed'] == 'True') / max(1, sum(1 for r in t.values() if r['round1_passed'] in ('True', 'False'))) for t in mv]
        md += ['', f'## sqlverify: verifier verdicts ({len(mv)} trial(s)) and the second round', '',
               f"- Questions with no verifiable SQL (MongoDB / Python only / multi-database): {cnt['no_sql_checked']}",
               f"- Round-1 wrong: rejected {cnt['reject_wrong']}, accepted {cnt['accept_wrong']} (false accepts)",
               f"- Round-1 right: rejected {cnt['reject_right']} (false rejects), accepted {cnt['accept_right']}",
               f"- Second round: wrong->right {cnt['round2_wrong_to_right']}, wrong->wrong {cnt['round2_wrong_to_wrong']}, "
               f"right->wrong {cnt['round2_right_to_wrong']}, right->right {cnt['round2_right_to_right']}",
               '- Round-1 accuracy (before any second round): ' + ', '.join(f'trial {i + 1} {x:.1%}' for i, x in enumerate(acc_r1))]
        summary['sqlverify_verdicts'] = dict(cnt); summary['sqlverify_round1_accuracy'] = acc_r1
        vc = [RES / 'haiku-claude-sqlverify-104x3' / f'trial{t}' / 'verifier_cost.json' for t in (1, 2)]
        summary['sqlverify_verifier_cost_usd'] = [json.loads(p.read_text())['verifier_cost_usd_estimate'] if p.exists() else None for p in vc]
    for m in ('fdj', 'docetl'):
        p = RES / 'method-prep' / m / 'summary.json'
        if p.exists():
            s = json.loads(p.read_text())
            summary[f'{m}_prep'] = s
            md += ['', f'## {m} preprocessing (once per dataset, Haiku)', '', f"- LLM cost estimate: ${s.get('cost_usd', 0):.2f}"]
            md += [f"- {k}: {v}" for k, v in s.get('specs', {}).items()]
    (OUT / 'COMPARISON.md').write_text('\n'.join(md) + '\n')
    (OUT / 'summary.json').write_text(json.dumps(summary, indent=2, default=str) + '\n')
    print('\n'.join(md))


if __name__ == '__main__':
    main()
