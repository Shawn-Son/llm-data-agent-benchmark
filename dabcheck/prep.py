"""Dataset-level preprocessing for the fdj and docetl conditions (run once, before any agent session).

    python -m dabcheck.prep --method fdj    --dab-root DIR --out DIR --dry-run
    python -m dabcheck.prep --method docetl --dab-root DIR --out DIR --budget 5

Writes <out>/<method>/<dataset>/: one CSV per spec, <spec>.json with the statistics, README.md
for the agent, and MANIFEST.json (status of every spec of the dataset). A spec that fails or hits a
cap is recorded with its status and produces no CSV; the agent then gets only what succeeded.
"""
from __future__ import annotations
import argparse, csv, json, math, os, random, re, sys, time, traceback
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from .dabdata import DABDataset
from .specs import SPECS


# ---------------------------------------------------------------- blocking helpers (FDJ)

def _norm(v: Any) -> str: return re.sub(r'[^0-9a-z]', '', str(v).lower())


def _grams(s: str, n: int = 3) -> set: return {s[i:i + n] for i in range(max(1, len(s) - n + 1))} if s else set()


class TrigramIndex:
    """Character-trigram inverted index over the right side; top-k candidates per left value."""

    def __init__(self, R: Sequence[Any], max_postings: int = 200):
        self.R = R; self.index: Dict[str, List[int]] = defaultdict(list)
        for j, r in enumerate(R):
            for g in _grams(_norm(r)): self.index[g].append(j)
        # drop uninformative grams; a fixed posting cap keeps one lookup O(grams x cap) on large tables
        self.index = {g: js for g, js in self.index.items() if len(js) <= max_postings}

    def top(self, value: Any, k: int) -> List[int]:
        score: Dict[int, int] = defaultdict(int)
        for g in _grams(_norm(value)):
            for j in self.index.get(g, ()): score[j] += 1
        return [j for j, _ in sorted(score.items(), key=lambda x: -x[1])[:k]]


def _record_text(r: Any) -> str:
    return ' | '.join(f'{k}: {v}' for k, v in r.items()) if isinstance(r, dict) else str(r)


# ---------------------------------------------------------------- FDJ job

def load_fdj_sides(ds: DABDataset, spec: Dict[str, Any]):
    if 'self' in spec:
        alias, table, cols = spec['self']
        rows = ds.rows(alias, table, cols)
        if spec.get('distinct'):
            seen, uniq = set(), []
            for r in rows:
                key = json.dumps(r, sort_keys=True, default=str)
                if key not in seen and any(v not in (None, '') for v in r.values()): seen.add(key); uniq.append(r)
            rows = uniq
        return rows, rows, True
    la, lt, lc = spec['left']; ra, rt, rc = spec['right']
    L = [v for v in ds.column(la, lt, lc) if v not in (None, '')]
    R = [v for v in ds.column(ra, rt, rc) if v not in (None, '')]
    return L, R, False


def run_fdj(ds: DABDataset, spec: Dict[str, Any], llm, out_dir: Path, *, dry_run: bool, caps: Dict[str, Any]) -> Dict[str, Any]:
    from .fdj import fdj_join
    t0 = time.time()
    L, R, is_self = load_fdj_sides(ds, spec)
    nL, nR = len(L), len(R)
    info: Dict[str, Any] = {'name': spec['name'], 'kind': 'fdj', 'left_size': nL, 'right_size': nR, 'cross_product': nL * nR,
                            'self_join': is_self, 'predicate': spec['predicate']}
    if dry_run:
        info['status'] = 'dry_run'; info['seconds'] = round(time.time() - t0, 1); return info
    if nL == 0 or nR == 0:
        info['status'] = 'empty'; return info
    Ltext = [_record_text(x) for x in L] if is_self else L
    Rtext = [_record_text(x) for x in R] if is_self else R
    index = TrigramIndex(Rtext)
    k = caps['block_k']

    def candidates():   # sparse joins: positives for the training sample and the blocked evaluation space
        rng = random.Random(1)
        left = list(range(nL)) if nL <= caps['candidate_left'] else rng.sample(range(nL), caps['candidate_left'])
        return [(i, j) for i in left for j in index.top(Ltext[i], k) if not (is_self and j <= i)]

    def space():        # the evaluation space used only when the scaffold has no exact hash-join block
        out = []
        for i in range(nL):
            for j in index.top(Ltext[i], k):
                if is_self and j <= i: continue
                out.append((i, j))
        return out
    use_space = space if nL * nR > caps['max_cross'] else None
    if use_space is not None: info['evaluation'] = f'blocked: top-{k} trigram candidates per left value (cross product {nL * nR} > {caps["max_cross"]})'
    try:
        res = fdj_join(Ltext, Rtext, spec['predicate'], llm, T=caps['recall_target'], delta=0.1, generate=True,
                       max_uniform=caps['max_uniform'], candidates_fn=candidates, pair_space=use_space,
                       max_refine=caps['max_refine'], seed=0)
    except Exception as e:   # BudgetExceeded, no featurization, API failure: record, deliver nothing
        info.update(status='failed', error=f'{type(e).__name__}: {e}'[:500], trace=traceback.format_exc()[-1500:])
        info['seconds'] = round(time.time() - t0, 1); return info
    matches = [(i, j) for i, j in res.matches if not (is_self and j <= i)]
    info.update(status='ok', summary=res.summary(), refined=getattr(res, 'refined', True), matches=len(matches),
                featurizations=[{'name': f.name, 'distance': f.distance, 'description': getattr(f, 'description', '')} for f in res.featurizations],
                log=res.log[-30:], seconds=round(time.time() - t0, 1))
    csv_path = out_dir / f"fdj_{spec['name']}.csv"
    with csv_path.open('w', newline='') as f:
        w = csv.writer(f)
        if is_self:
            idc = spec['id']
            # connected components of the match graph = clusters of records that refer to the same entity
            parent = list(range(nL))
            def find(x):
                while parent[x] != x: parent[x] = parent[parent[x]]; x = parent[x]
                return x
            for i, j in matches: parent[find(i)] = find(j)
            w.writerow([idc, 'cluster_id'])
            for i, r in enumerate(L): w.writerow([r[idc], find(i)])
            info['clusters'] = len({find(i) for i in range(nL)})
        else:
            w.writerow(['left_value', 'right_value'])
            for i, j in matches: w.writerow([L[i], R[j]])
            info['left_matched'] = len({i for i, _ in matches}); info['right_matched'] = len({j for _, j in matches})
    info['csv'] = csv_path.name
    return info


# ---------------------------------------------------------------- DocETL job

def run_docetl(ds: DABDataset, spec: Dict[str, Any], llm, out_dir: Path, *, dry_run: bool, caps: Dict[str, Any]) -> Dict[str, Any]:
    from .extract import ExtractSpec, extract_values
    t0 = time.time()
    alias, table, id_cols, text_col = spec['source']
    rows = ds.rows(alias, table, list(id_cols) + [text_col])
    texts = [r[text_col] for r in rows]
    info: Dict[str, Any] = {'name': spec['name'], 'kind': 'docetl', 'rows': len(rows), 'source': f'{alias}.{table}.{text_col}', 'fields': {}}
    results = {}
    for e in spec['extract']:
        es = ExtractSpec(e['name'], patterns=e.get('patterns', []), parse=e['parse'], description=e.get('description', ''), unit=e.get('unit', ''))
        code = extract_values(texts, es, llm=None)
        field = {'code_coverage': code.coverage['coverage'], 'unparsed_rows': sum(1 for r in code.rows if r['value'] is None)}
        if dry_run:
            field['status'] = 'dry_run'; field['unparsed_samples'] = code.coverage.get('unparsed_samples', [])[:5]
            info['fields'][e['name']] = field; continue
        try:
            res = extract_values(texts, es, llm=llm, use_llm=True, gleaning_rounds=1, max_llm_rows=caps['max_llm_rows'],
                                 context=f'This text comes from the column {table}.{text_col} of the {ds.name} dataset.',
                                 workers=caps['workers'])
            field.update(status='ok', summary=res.summary(), llm_rows=res.llm_rows)
            results[e['name']] = res
        except Exception as ex:
            field.update(status='failed', error=f'{type(ex).__name__}: {ex}'[:500])
            results[e['name']] = code; field['fallback'] = 'code-only values'
        info['fields'][e['name']] = field
    info['seconds'] = round(time.time() - t0, 1)
    if dry_run: info['status'] = 'dry_run'; return info
    csv_path = out_dir / f"docetl_{spec['name']}.csv"
    names = [e['name'] for e in spec['extract']]
    with csv_path.open('w', newline='') as f:
        w = csv.writer(f)
        w.writerow(list(id_cols) + [text_col] + [x for n in names for x in (n, n + '_source')])
        for i, r in enumerate(rows):
            vals = []
            for n in names:
                rr = results[n].rows[i]; vals += [rr['value'], rr.get('source')]
            w.writerow([r[c] for c in id_cols] + [r[text_col]] + vals)
    info['status'] = 'ok' if all(v.get('status') == 'ok' for v in info['fields'].values()) else 'partial'
    info['csv'] = csv_path.name
    return info


# ---------------------------------------------------------------- README for the agent

def readme(method: str, dataset: str, items: List[Dict[str, Any]]) -> str:
    title = {'fdj': 'Precomputed semantic joins (FDJ)', 'docetl': 'Precomputed text extraction (DocETL)'}[method]
    lines = [f'# {title} for {dataset}', '',
             'These files were produced once, before your session, by an automatic preprocessing step that used an LLM.',
             'They are machine-generated and can contain errors or gaps. Use them where they help, check them against the',
             'data, and say in your answer if your result depends on them.', '']
    for it in items:
        if it.get('status') not in ('ok', 'partial') or not it.get('csv'): continue
        if it['kind'] == 'fdj':
            s = it.get('summary', {})
            if it.get('self_join'):
                lines.append(f"- `{it['csv']}`: groups records that refer to the same entity ({it['predicate']}). "
                             f"Columns: record id, cluster_id (same cluster_id = same entity). {it.get('clusters')} clusters over {it['left_size']} records.")
            else:
                lines.append(f"- `{it['csv']}`: pairs (left_value, right_value) judged to satisfy: {it['predicate']} "
                             f"{it.get('matches')} pairs; {it.get('left_matched')} of {it['left_size']} distinct left values matched; "
                             f"target recall {s.get('adjusted_target', 'n/a')}, recall on the labelled sample {s.get('sample_recall')}"
                             f"{'' if it.get('refined', True) else '; pairs were NOT individually confirmed (too many candidates)'}.")
        else:
            fields = ', '.join(f"{n} (coverage {v.get('summary', {}).get('final_coverage', v.get('code_coverage', 0)):.0%})" for n, v in it['fields'].items())
            lines.append(f"- `{it['csv']}`: values extracted from {it['source']} ({it['rows']} rows): {fields}. "
                         f"Each value has a *_source column: code (regex/parser), llm (LLM with a verbatim evidence check), or empty (not stated).")
    if len(lines) == 6: lines.append('- (no output: the preprocessing produced nothing usable for this dataset)')
    return '\n'.join(lines) + '\n'


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument('--method', choices=sorted(SPECS), required=True)
    p.add_argument('--dab-root', default=os.environ.get('DAB_ROOT', '/home/minhyeok/dab-reproduction'))
    p.add_argument('--out', required=True)
    p.add_argument('--dataset', action='append', help='limit to these datasets')
    p.add_argument('--spec', action='append', help='limit to these spec names')
    p.add_argument('--dry-run', action='store_true', help='sizes and code-only coverage, no LLM calls')
    p.add_argument('--model', default='claude-haiku-5-5')
    p.add_argument('--budget', type=float, default=5.0, help='USD cap for this run (all specs together)')
    p.add_argument('--spec-budget', type=float, default=None, help='USD cap per spec (a costly spec cannot starve the others)')
    p.add_argument('--workers', type=int, default=8, help='concurrent LLM calls for per-row extraction')
    p.add_argument('--max-uniform', type=int, default=2000)
    p.add_argument('--max-refine', type=int, default=20000)
    p.add_argument('--max-cross', type=int, default=20_000_000)
    p.add_argument('--block-k', type=int, default=10)
    p.add_argument('--candidate-left', type=int, default=3000)
    p.add_argument('--max-llm-rows', type=int, default=20000)
    a = p.parse_args(argv)
    caps = {'max_uniform': a.max_uniform, 'max_refine': a.max_refine, 'max_cross': a.max_cross, 'block_k': a.block_k,
            'candidate_left': a.candidate_left, 'recall_target': 0.9, 'max_llm_rows': a.max_llm_rows, 'workers': a.workers,
            'spec_budget': a.spec_budget}
    llm = None
    if not a.dry_run:
        from .llm import LLM
        llm = LLM(model=a.model, cheap_model=a.model, allowed_models={a.model}, budget_usd=a.budget)
    specs = [s for s in SPECS[a.method] if (not a.dataset or s['dataset'] in a.dataset) and (not a.spec or s['name'] in a.spec)]
    by_ds: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for s in specs: by_ds[s['dataset']].append(s)
    root = Path(a.out) / a.method
    report = {}
    for dsname, items in sorted(by_ds.items()):
        ds = DABDataset(a.dab_root, dsname)
        out_dir = root / dsname; out_dir.mkdir(parents=True, exist_ok=True)
        manifest_path = out_dir / 'MANIFEST.json'
        manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {'dataset': dsname, 'method': a.method, 'specs': {}}
        for s in items:
            print('START', a.method, dsname, s['name'], flush=True)
            fn = run_fdj if a.method == 'fdj' else run_docetl
            if llm is not None:   # per-spec cap on top of the run cap
                llm.budget_usd = a.budget if a.spec_budget is None else min(a.budget, llm.usage.cost_usd + a.spec_budget)
            try: info = fn(ds, s, llm, out_dir, dry_run=a.dry_run, caps=caps)
            except Exception as e:
                info = {'name': s['name'], 'status': 'failed', 'error': f'{type(e).__name__}: {e}'[:500], 'trace': traceback.format_exc()[-1500:]}
            if llm is not None: info['usage_after'] = llm.usage.as_dict()
            print('DONE', a.method, dsname, s['name'], json.dumps({k: info.get(k) for k in ('status', 'left_size', 'right_size', 'rows', 'matches', 'error', 'seconds')}), flush=True)
            if not a.dry_run:
                (out_dir / f"{s['name']}.json").write_text(json.dumps(info, indent=2, default=str) + '\n')
                manifest['specs'][s['name']] = {k: info.get(k) for k in ('status', 'csv', 'error')}
            report[f'{dsname}/{s["name"]}'] = info
        if not a.dry_run:
            infos = [json.loads((out_dir / f"{n}.json").read_text()) for n in manifest['specs'] if (out_dir / f"{n}.json").exists()]
            (out_dir / 'README.md').write_text(readme(a.method, dsname, infos))
            manifest['model'] = a.model; manifest['caps'] = caps
            manifest_path.write_text(json.dumps(manifest, indent=2) + '\n')
    summary = {'method': a.method, 'dry_run': a.dry_run, 'usage': llm.usage.as_dict() if llm else None, 'specs': report}
    (root.mkdir(parents=True, exist_ok=True))
    (root / ('dry_run.json' if a.dry_run else f'run-{time.strftime("%Y%m%dT%H%M%S")}.json')).write_text(json.dumps(summary, indent=2, default=str) + '\n')
    print('PREP_SUMMARY', json.dumps({'usage': summary['usage'], 'statuses': {k: v.get('status') for k, v in report.items()}}), flush=True)


if __name__ == '__main__':
    main()
