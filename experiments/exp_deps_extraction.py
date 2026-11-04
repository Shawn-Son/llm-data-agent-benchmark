"""DEPS_DEV_V1 q1 / q2 (Extraction): star and fork counts embedded in prose.

Reproduces the Haiku failure (`(\\d+) forks` captures 522 of "30,522 forks") and shows that the
code-first pipeline with a coverage report recovers every count; the fork top-5 is checked against
the official ground truth of q2 (project names + ForksCount).
"""
import csv, duckdb, re
from common import dataset, save, DAB, Timer
from dabcheck.extract import ExtractSpec, CodeExtractor, coverage_report, extract_values

NAIVE_FORKS = ExtractSpec('forks', patterns=[r'(?P<value>\d+) forks'], parse='int')
FORKS = ExtractSpec('forks', patterns=[r'(?P<value>\d{1,3}(?:,\d{3})+|\d+)\s+forks?\b', r'forks?\s+count\s+(?:of|is|:)?\s*(?P<value>\d{1,3}(?:,\d{3})+|\d+)',
                                       r'forked\s+(?P<value>\d{1,3}(?:,\d{3})+|\d+)\s+times'], parse='int')
STARS = ExtractSpec('stars', patterns=[r'(?P<value>\d{1,3}(?:,\d{3})+|\d+)\s+stars?\b', r'stars?\s+count\s+(?:of|is|:)?\s*(?P<value>\d{1,3}(?:,\d{3})+|\d+)',
                                       r'starred\s+(?P<value>\d{1,3}(?:,\d{3})+|\d+)\s+times'], parse='int')
NAME = ExtractSpec('project', patterns=[r'project\s+(?P<value>[\w.\-]+/[\w.\-]+)', r'(?P<value>[\w.\-]+/[\w.\-]+)'], parse='text')


def main():
    t = Timer()
    con = duckdb.connect(str(dataset('DEPS_DEV_V1') / 'project_query.db'), read_only=True)
    texts = [r[0] or '' for r in con.execute('SELECT Project_Information FROM project_info').fetchall()]
    names = [r['value'] for r in (CodeExtractor(NAME)(t) for t in texts)]   # the project name is only stated in the prose
    out = {}
    for label, spec in (('naive_forks', NAIVE_FORKS), ('forks', FORKS), ('stars', STARS)):
        res = extract_values(texts, spec, llm=None)
        out[label] = {'summary': res.summary(), 'coverage': res.coverage}
    forks = extract_values(texts, FORKS, llm=None).values(); naive = extract_values(texts, NAIVE_FORKS, llm=None).values()
    # ground truth for q2 (top-5 fork counts among MIT release packages) lists the true fork counts of five projects
    gt = {}
    gtp = DAB / 'query_DEPS_DEV_V1' / 'query2' / 'ground_truth.csv'
    if gtp.exists():
        with open(gtp, encoding='utf-8-sig') as f:
            for r in csv.DictReader(f): gt[r['ProjectName']] = int(r['ForksCount'])
    by_name = {n: (v, nv) for n, v, nv in zip(names, forks, naive)}
    checks = [{'project': p, 'ground_truth': g, 'pipeline': by_name.get(p, (None, None))[0], 'naive_regex': by_name.get(p, (None, None))[1]} for p, g in gt.items()]
    out['ground_truth_check'] = checks
    out['seconds'] = t()
    md = ['# DEPS_DEV_V1 fork / star extraction (offline)', '', f'rows: {len(texts)}', '',
          '| extractor | coverage | suspected truncations | warnings |', '|---|---:|---:|---|']
    for k in ('naive_forks', 'forks', 'stars'):
        c = out[k]['coverage']; md.append(f"| {k} | {c['coverage']:.1%} | {c['suspected_truncations']} | {'; '.join(c['warnings']) or '-'} |")
    md += ['', '| project (q2 ground truth) | true forks | pipeline | naive `(\\d+) forks` |', '|---|---:|---:|---:|']
    for c in checks: md.append(f"| {c['project']} | {c['ground_truth']} | {c['pipeline']} | {c['naive_regex']} |")
    unparsed = out['forks']['coverage']['unparsed_samples']
    md += ['', 'Unparsed samples (forks pipeline): ' + ('; '.join(s[:100] for s in unparsed) if unparsed else 'none')]
    save('deps_extraction', out, '\n'.join(md) + '\n'); print('\n'.join(md))


if __name__ == '__main__': main()
