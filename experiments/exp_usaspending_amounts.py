"""usaspending q1 (Extraction): contract_amounts.amount_text.

The hint promises exact, parseable amounts; the data is ~95% vague magnitude prose. The code
extractor parses every exact format and the coverage report says, before any aggregation, that
the answer would rest on a small subset of rows (the Haiku runs' "71 lower bound" and terra's
keyword bands both followed from this). No LLM needed to raise the warning.
"""
from common import dataset, save, Timer
from dabcheck.util.pgdump import load_pgdump
from dabcheck.extract import ExtractSpec, extract_values, parse_amount
from dabcheck.fdj import audit_join


def main():
    t = Timer()
    con = load_pgdump(str(dataset('usaspending') / 'contracts.sql'))
    amounts = con.execute('SELECT award_id, amount_text FROM contract_amounts').fetchall()
    contracts = [r[0] for r in con.execute('SELECT award_id FROM contracts')]
    spec = ExtractSpec('award_amount', parse='amount', unit='USD', min_coverage=0.95)
    res = extract_values([a for _, a in amounts], spec, llm=None)
    vals = res.values()
    numeric = [v for v in vals if v is not None]
    join = audit_join(contracts, [a for a, _ in amounts], left_name='contracts.award_id', right_name='contract_amounts.award_id')
    out = {'rows': len(amounts), 'summary': res.summary(), 'coverage': res.coverage,
           'numeric_rows': len(numeric), 'numeric_over_1M': sum(1 for v in numeric if v > 1_000_000),
           'old_suffix_rows': sum(1 for a, _ in amounts if str(a).endswith('_OLD')), 'join_audit': join, 'seconds': t()}
    md = ['# usaspending amount_text extraction (offline)', '', f"rows: {len(amounts)}; exact-format rows parsed by code: {len(numeric)} "
          f"({res.coverage['coverage']:.1%}); numeric rows > $1M: {out['numeric_over_1M']}; rows with _OLD suffix: {out['old_suffix_rows']}", '',
          'Warnings:'] + [f'- {w}' for w in res.warnings] + ['', 'Unparsed samples:'] + [f'- {s}' for s in res.coverage['unparsed_samples']]
    md += ['', 'award_id join audit (contracts vs contract_amounts):', f"best rule {join['best_rule']}: " +
           ', '.join(f"{k}={v['matched_keys']}" for k, v in join['rules'].items())] + [f'- {w}' for w in join['warnings']]
    save('usaspending_amounts', out, '\n'.join(md) + '\n'); print('\n'.join(md))


if __name__ == '__main__': main()
