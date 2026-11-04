"""Live evaluation of the three modules with claude-haiku-5-5 (needs an API key).

Stages (run all or pick with --stages):
  verify    SQL verifiers on question / SQL pairs with a known right and wrong query:
            crmarenapro q12 (date field), civic q4 window (inclusive end), imdb keyword join (integer ids).
            Reports per-method accept/reject -> false accepts / false rejects, and cost.
  extract   LLM fallback of the extraction pipeline on rows the code could not parse
            (usaspending prose amounts: the correct answer is null; DEPS naive-pattern misses).
  optimizer DocETL optimizer on the DEPS star/fork extraction map over a small sample
            (does the validation agent gate it, which rewrite wins).
  fdj       FDJ with Haiku as reasoning, extraction and labelling model on the cve KEV x vulns join,
            scored against the oracle built from DAB's corruption code; refinement is capped.
A spend cap (--budget, USD, default 5) stops the run between stages; every reply is cached, so a
re-run after a stop does not pay again.
"""
import argparse, json, os, random, re, sqlite3, sys, time
from pathlib import Path
from common import dataset, save, DAB, Timer, RESULTS
os.environ.setdefault('DABCHECK_MODEL', 'claude-haiku-5-5'); os.environ.setdefault('DABCHECK_CHEAP_MODEL', 'claude-haiku-5-5')
from dabcheck.llm import LLM
from dabcheck.sqlverify import schema_from_sqlite, schema_from_duckdb, verify_sql, Schema, Table, Column
from dabcheck.extract import ExtractSpec, extract_values, optimize_map
from dabcheck.util.pgdump import load_pgdump

CASES = []  # (name, question, schema, right_sql, wrong_sql, note)


def crm_case():
    db = str(dataset('crmarenapro') / 'sales_pipeline.duckdb')
    sc = schema_from_duckdb(db, tables=['Opportunity', 'Contract']); sc.dialect = 'sqlite'
    q = ("Who had the quickest average turnaround from opening to closing opportunities among agents in April 2023? "
         "Return only the Id of the agent. Sales Cycle Policy: the sales cycle is measured as the number of days between an "
         "opportunity's creation date and the company signed date on the corresponding contract.")
    # both queries return only the agent Id, so the verifiers judge the date-field choice, not an extra column
    right = """SELECT agent FROM (SELECT o.OwnerId AS agent, AVG(julianday(c.CompanySignedDate) - julianday(o.CreatedDate)) AS avg_days
FROM Opportunity o JOIN Contract c ON c.Id = o.ContractID__c
WHERE c.CompanySignedDate >= '2023-04-01' AND c.CompanySignedDate < '2023-05-01' GROUP BY o.OwnerId ORDER BY avg_days LIMIT 1)"""
    wrong = right.replace("c.CompanySignedDate >= '2023-04-01' AND c.CompanySignedDate < '2023-05-01'",
                          "o.CreatedDate >= '2023-04-01' AND o.CreatedDate < '2023-05-01'")
    return ('crmarenapro_q12_date_field', q, sc, right, wrong, 'month anchored on signing date vs creation date')


def civic_case():
    db = str(dataset('civic_unstructured') / 'funding.db')
    sc = schema_from_sqlite(db)
    q = "What is the total funding amount (USD) granted between 2021-06-01 and 2022-06-01 (inclusive) across all funding records?"
    right = "SELECT SUM(amount) FROM Funding WHERE grant_time >= '2021-06-01' AND grant_time <= '2022-06-01'"
    wrong = "SELECT SUM(amount) FROM Funding WHERE grant_time >= '2021-06-01' AND grant_time < '2022-06-01'"
    return ('civic_q4_inclusive_end', q, sc, right, wrong, 'inclusive end date dropped')


def imdb_case():
    sc = Schema(dialect='sqlite', notes=("Identifier columns use non-standard string encodings: keyword.id looks like 'kwd..2905' or "
                                         "'kwd...2068', movie_keyword.keyword_id like 'Kw00002083' or 'kw00001'. To join, extract the "
                                         "embedded integer by stripping the alphabetic prefix, punctuation padding and leading zeros."))
    sc.add(Table('keyword', [Column('id', 'text'), Column('keyword', 'text')], samples=[{'id': 'kwd...2068', 'keyword': 'handcuffed-to-a-bed'}, {'id': 'kwd..157', 'keyword': 'jane-austen'}]))
    sc.add(Table('movie_keyword', [Column('id', 'integer'), Column('movie_id', 'integer'), Column('keyword_id', 'text')], samples=[{'id': 1, 'movie_id': 2, 'keyword_id': 'kw00001'}, {'id': 2, 'movie_id': 11, 'keyword_id': 'Kw0002'}]))
    q = "How many distinct movies are tagged with the keyword 'superhero'?"
    right = ("SELECT COUNT(DISTINCT mk.movie_id) FROM movie_keyword mk JOIN keyword k "
             "ON CAST(REPLACE(REPLACE(REPLACE(REPLACE(LOWER(k.id), 'kwd', ''), '.', ''), 'kw', ''), '~', '') AS INTEGER) = "
             "CAST(REPLACE(REPLACE(REPLACE(LOWER(mk.keyword_id), 'kwd', ''), 'kw', ''), '.', '') AS INTEGER) WHERE k.keyword = 'superhero'")
    wrong = ("SELECT COUNT(DISTINCT mk.movie_id) FROM movie_keyword mk JOIN keyword k "
             "ON REPLACE(REPLACE(REPLACE(LOWER(k.id), 'kwd', ''), '.', ''), '~', '') = "
             "REPLACE(REPLACE(REPLACE(LOWER(mk.keyword_id), 'kwd', ''), 'kw', ''), '.', '') WHERE k.keyword = 'superhero'")
    return ('imdb_keyword_join_leading_zeros', q, sc, right, wrong, 'digit strings compared without dropping leading zeros')


def stage_verify(llm, out, budget):
    rows = []
    for name, q, sc, right, wrong, note in (crm_case(), civic_case(), imdb_case()):
        for kind, sql in (('right', right), ('wrong', wrong)):
            if llm.usage.cost_usd > budget: break
            t = Timer()
            v = verify_sql(llm, q, sql, sc, methods=('rt', 'se', 'sc', 'cohort'), combine='and', n_cases=2)
            per = {m: r['accept'] for m, r in v['methods'].items()}
            rows.append({'case': name, 'kind': kind, 'note': note, 'per_method': per, 'and': v['accept'],
                         'or': any(per.values()), 'reasons': v['reasons'], 'seconds': t(),
                         'rt_back_translation': v['methods']['rt'].get('back_translation'),
                         'se_cases': [{'note': c['note'], 'match': c['match'], 'error': c['error']} for c in v['methods']['se']['cases']],
                         'cohort_warnings': v['methods']['cohort'].get('warnings')})
            print(f"{name:40s} {kind:5s} " + ' '.join(f"{m}={'A' if a else 'R'}" for m, a in per.items()), flush=True)
    summary = {}
    for m in ('rt', 'se', 'sc', 'cohort', 'and', 'or'):
        get = (lambda r: r['per_method'][m]) if m in ('rt', 'se', 'sc', 'cohort') else (lambda r: r[m])
        fa = sum(1 for r in rows if r['kind'] == 'wrong' and get(r)); fr = sum(1 for r in rows if r['kind'] == 'right' and not get(r))
        nw = sum(1 for r in rows if r['kind'] == 'wrong'); nr = sum(1 for r in rows if r['kind'] == 'right')
        summary[m] = {'false_accepts': f'{fa}/{nw}', 'false_rejects': f'{fr}/{nr}'}
    out['verify'] = {'rows': rows, 'summary': summary, 'usage_after': llm.usage.as_dict()}


def stage_extract(llm, out, budget):
    con = load_pgdump(str(dataset('usaspending') / 'contracts.sql'))
    amounts = [r[0] for r in con.execute('SELECT amount_text FROM contract_amounts ORDER BY award_id LIMIT 400')]
    spec = ExtractSpec('award_amount', parse='amount', unit='USD')
    res = extract_values(amounts, spec, llm, gleaning_rounds=1, max_llm_rows=60)
    llm_rows = [(t, r) for t, r in zip(amounts, res.rows) if r['source'] == 'llm']
    out['extract_usaspending'] = {'rows': len(amounts), 'llm_attempted': res.llm_rows, 'llm_assigned_values': len(llm_rows),
                                  'examples_assigned': [{'text': t[:160], 'value': r['value'], 'evidence': r['raw']} for t, r in llm_rows[:8]],
                                  'summary': res.summary(), 'note': 'prose amounts are vague: a correct LLM returns null (assigned values are false extractions)'}
    import duckdb
    dc = duckdb.connect(str(dataset('DEPS_DEV_V1') / 'project_query.db'), read_only=True)
    texts = [r[0] or '' for r in dc.execute('SELECT Project_Information FROM project_info').fetchall()]
    naive = ExtractSpec('forks', patterns=[r'(?P<value>\d+) forks'], parse='int')
    res2 = extract_values(texts, naive, llm, gleaning_rounds=1, max_llm_rows=60)
    truth = ExtractSpec('forks', patterns=[r'(?P<value>\d{1,3}(?:,\d{3})+|\d+)\s+forks?\b', r'forks?\s+count\s+(?:of|is|:)?\s*(?P<value>\d{1,3}(?:,\d{3})+|\d+)', r'forked\s+(?P<value>\d{1,3}(?:,\d{3})+|\d+)\s+times'], parse='int')
    from dabcheck.extract import CodeExtractor
    code_truth = [CodeExtractor(truth)(t)['value'] for t in texts]
    checked = [(t, r, g) for t, r, g in zip(texts, res2.rows, code_truth) if r['source'] == 'llm']
    correct = sum(1 for t, r, g in checked if r['value'] == g)
    out['extract_deps'] = {'llm_rows': len(checked), 'llm_correct_vs_code_truth': correct,
                           'mismatches': [{'text': t[:160], 'llm': r['value'], 'truth': g} for t, r, g in checked if r['value'] != g][:8],
                           'summary': res2.summary(), 'usage_after': llm.usage.as_dict()}


def stage_optimizer(llm, out, budget):
    import duckdb
    dc = duckdb.connect(str(dataset('DEPS_DEV_V1') / 'project_query.db'), read_only=True)
    rng = random.Random(0)
    texts = [r[0] or '' for r in dc.execute('SELECT Project_Information FROM project_info').fetchall()]
    sample = [{'text': t} for t in rng.sample(texts, 5)]
    res = optimize_map(llm, 'Extract the GitHub project name, its star count and its fork count from: {{ input.text }}',
                       {'project': 'string', 'stars': 'integer', 'forks': 'integer'}, sample)
    out['optimizer_deps'] = {'plan': res['plan'], 'criteria': res['criteria'], 'assessment': res.get('assessment'),
                             'ratings': res.get('ratings'), 'wins': res.get('wins'),
                             'outputs': {k: [{kk: d.get(kk) for kk in ('project', 'stars', 'forks')} for d in v] for k, v in res['outputs'].items()},
                             'usage_after': llm.usage.as_dict()}


def stage_fdj(llm, out, budget, max_candidates=20000):
    sys.path.insert(0, str(Path(__file__).parent))
    from exp_cve_fdj import load_corrupt, _CVE_NOTE
    from dabcheck.fdj import fdj_join
    corrupt = load_corrupt(); rng = random.Random(0)
    kev = load_pgdump(str(dataset('cve') / 'kev.sql')).execute('SELECT cve_ref, notes FROM kev_entries').fetchall()
    vul = sqlite3.connect(f"file:{dataset('cve') / 'vulns.db'}?mode=ro", uri=True)
    vulns_keys = [r[0] for r in vul.execute('SELECT cve_id FROM cves')]; vulns_set = set(vulns_keys)
    partner = {}
    for ref, notes in kev:
        m = _CVE_NOTE.findall(notes or '')
        if not m: continue
        cid = f'CVE-{m[-1][0]}-{m[-1][1]}'; vk = corrupt.reformat_cve_id(cid, 'vulns-' + cid)
        if vk in vulns_set: partner[ref] = vk
    L = [ref for ref, _ in kev][:400]                      # a 400 x 1000 slice keeps the Haiku spend small
    partners = sorted({partner[l] for l in L if l in partner})
    others = [k for k in vulns_keys if k not in set(partners)]
    R = partners + rng.sample(others, 1000 - len(partners)); rng.shuffle(R)
    Rpos = {k: j for j, k in enumerate(R)}
    truth = {(i, Rpos[partner[l]]) for i, l in enumerate(L) if l in partner}
    oracle = lambda l, r: int(partner.get(l) == r)
    import threading
    haiku_labels = {'n': 0, 'agree': 0}; lock = threading.Lock()
    from dabcheck.fdj.join import llm_labeler, _label_many
    from dabcheck.fdj.featurize import WORKERS
    hl = llm_labeler(llm, 'Do these two noisy keys encode the same CVE identifier (the same CVE-YYYY-NNNN)? Keys carry random prefixes, '
                          'suffixes, wrapper text, inserted noise fragments, and the year/number may be re-encoded (offsets, reversal, '
                          'base-36, hex, interleaving, OCR-like character substitutions).')

    def labeler(l, r):   # Haiku labels; agreement with the oracle is recorded
        y = hl(l, r)
        with lock: haiku_labels['n'] += 1; haiku_labels['agree'] += int(y == oracle(l, r))
        return y
    t = Timer()
    res = fdj_join(L, R, 'same CVE identifier', llm, labeler=labeler, T=0.9, delta=0.1, min_train_pos=40, n_train_neg=400,
                   batch=100, max_uniform=1500, discovery_pos=20, discovery_neg=80, candidates_fn=lambda: sorted(truth),
                   max_iter=3, refine=False, seed=0)
    cands = set(res.candidates)
    cand_recall = len(cands & truth) / max(1, len(truth)); cand_precision = len(cands & truth) / max(1, len(cands))
    refined = None
    if len(cands) <= max_candidates and llm.usage.cost_usd < budget:   # refinement: Haiku confirms every candidate (Alg. 5 line 10)
        ys = _label_many(labeler, L, R, res.candidates, WORKERS)
        matches = [p for p, y in zip(res.candidates, ys) if y]
        refined = {'matches': len(matches), 'recall': len(set(matches) & truth) / max(1, len(truth)),
                   'precision': len(set(matches) & truth) / max(1, len(matches)), 'refinement_calls': len(res.candidates)}
    else:
        refined = {'skipped': f'{len(cands)} candidates exceed the cap of {max_candidates} or the budget'}
    out['fdj_cve'] = {'L': len(L), 'R': len(R), 'true_pairs': len(truth), 'features': [{'name': f.name, 'distance': f.distance, 'left': f.left.kind, 'right': f.right.kind, 'description': f.description} for f in res.featurizations],
                      'decomposition': res.scaffold.describe(res.featurizations), 'adjusted_target': res.adjusted_target, 'sample_recall': res.sample_recall,
                      'target_feasible': res.target_feasible, 'labeled_pairs': res.n_labeled, 'haiku_label_agreement_with_oracle': haiku_labels,
                      'candidates': len(cands), 'candidate_recall_vs_oracle': cand_recall, 'candidate_precision_vs_oracle': cand_precision,
                      'refined': refined, 'log': res.log, 'seconds': t(), 'usage_after': llm.usage.as_dict()}


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--stages', default='verify,extract,optimizer,fdj'); ap.add_argument('--budget', type=float, default=5.0)
    a = ap.parse_args()
    llm = LLM()
    out = {'model': llm.model, 'cheap_model': llm.cheap_model}
    for st in a.stages.split(','):
        if llm.usage.cost_usd > a.budget: print('budget reached before', st); break
        print(f'=== stage {st} (spent so far ${llm.usage.cost_usd:.3f})', flush=True)
        globals()['stage_' + st](llm, out, a.budget)
        save('live_haiku_eval', {**out, 'usage': llm.usage.as_dict()})
    out['usage'] = llm.usage.as_dict()
    md = ['# Live evaluation with claude-haiku-5-5', '', f"Spend (estimate): ${out['usage']['cost_usd']:.3f}; calls {out['usage']['calls']} (+{out['usage']['cached_calls']} cached)", '']
    if 'verify' in out:
        md += ['## SQL verifiers (A = accept, R = reject)', '', '| case | kind | rt | se | sc | cohort | AND | OR |', '|---|---|---|---|---|---|---|---|']
        for r in out['verify']['rows']:
            p = r['per_method']; md.append(f"| {r['case']} | {r['kind']} | {'A' if p['rt'] else 'R'} | {'A' if p['se'] else 'R'} | {'A' if p['sc'] else 'R'} | {'A' if p['cohort'] else 'R'} | {'A' if r['and'] else 'R'} | {'A' if r['or'] else 'R'} |")
        md += ['', '| method | false accepts | false rejects |', '|---|---|---|'] + [f"| {m} | {v['false_accepts']} | {v['false_rejects']} |" for m, v in out['verify']['summary'].items()]
    if 'extract_usaspending' in out:
        e = out['extract_usaspending']; md += ['', f"## Extraction fallback: usaspending prose amounts: {e['llm_attempted']} rows sent to Haiku, {e['llm_assigned_values']} got a value (should be 0)"]
        e = out['extract_deps']; md += [f"DEPS naive pattern misses: {e['llm_rows']} rows sent to Haiku, {e['llm_correct_vs_code_truth']} agree with the code extraction"]
    if 'optimizer_deps' in out:
        o = out['optimizer_deps']; md += ['', f"## DocETL optimizer on DEPS: plan = {o['plan']}, gate = {o['assessment']}, ratings = {o.get('ratings')}, wins = {o.get('wins')}"]
    if 'fdj_cve' in out:
        f = out['fdj_cve']; md += ['', '## FDJ on cve with Haiku', f"features: {[x['name'] + ' (' + x['left'] + '/' + x['right'] + ', ' + x['distance'] + ')' for x in f['features']]}",
                                   f"decomposition: {f['decomposition']}; T' = {f['adjusted_target']:.3f}; feasible = {f['target_feasible']}",
                                   f"labelled pairs {f['labeled_pairs']}; Haiku label agreement with oracle {f['haiku_label_agreement_with_oracle']}",
                                   f"candidates {f['candidates']} of {f['L'] * f['R']} pairs; candidate recall {f['candidate_recall_vs_oracle']:.3f}, precision {f['candidate_precision_vs_oracle']:.3f}; refined = {f['refined']}"]
    save('live_haiku_eval', out, '\n'.join(md) + '\n'); print('\n'.join(md))


if __name__ == '__main__': main()
