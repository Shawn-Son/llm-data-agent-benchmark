"""crmarenapro q12 (Temporal state): "quickest average turnaround ... among agents in April 2023".

All four runs filtered opportunities *created* in April 2023; the policy anchors the month on the
contract's CompanySignedDate (closing). Offline parts of the verification stack:
  1. both SQLs run on the real DuckDB: they name different agents (the disagreement itself is a signal);
  2. synthetic execution with a hand-written test case of the kind the LLM generator produces: the
     signed-date SQL reproduces the expected answer, the created-date SQL does not;
  3. intent cards compared deterministically: the date-field mismatch is reported.
The LLM-backed steps (back-translation, card extraction, case generation) need an API key and are
left to `python -m dabcheck verify-sql`.
"""
import duckdb
from common import dataset, save, Timer
from dabcheck.sqlverify import schema_from_duckdb, execute_sql, results_match, synthetic_execution_verify, compare_cards

SQL_SIGNED = """
SELECT o.OwnerId AS agent, AVG(date_diff('day', CAST(o.CreatedDate AS DATE), CAST(c.CompanySignedDate AS DATE))) AS avg_days
FROM Opportunity o JOIN Contract c ON regexp_replace(trim(c.Id), '^#', '') = regexp_replace(trim(o.ContractID__c), '^#', '')
WHERE CAST(c.CompanySignedDate AS DATE) >= DATE '2023-04-01' AND CAST(c.CompanySignedDate AS DATE) < DATE '2023-05-01'
GROUP BY o.OwnerId ORDER BY avg_days ASC LIMIT 1"""
SQL_CREATED = SQL_SIGNED.replace("CAST(c.CompanySignedDate AS DATE) >= DATE '2023-04-01' AND CAST(c.CompanySignedDate AS DATE) < DATE '2023-05-01'",
                                 "CAST(o.CreatedDate AS DATE) >= DATE '2023-04-01' AND CAST(o.CreatedDate AS DATE) < DATE '2023-05-01'")
# sqlite-dialect equivalents for the synthetic executor
SQL_SIGNED_LITE = """SELECT o.OwnerId AS agent, AVG(julianday(c.CompanySignedDate) - julianday(o.CreatedDate)) AS avg_days
FROM Opportunity o JOIN Contract c ON c.Id = o.ContractID__c
WHERE c.CompanySignedDate >= '2023-04-01' AND c.CompanySignedDate < '2023-05-01' GROUP BY o.OwnerId ORDER BY avg_days LIMIT 1"""
SQL_CREATED_LITE = SQL_SIGNED_LITE.replace("c.CompanySignedDate >= '2023-04-01' AND c.CompanySignedDate < '2023-05-01'",
                                           "o.CreatedDate >= '2023-04-01' AND o.CreatedDate < '2023-05-01'")
CASE = {'mode': 'answer_first', 'note': 'an opportunity created in April but signed in June must not count; one created in January and signed in April must',
        'tables': {'Opportunity': [{'Id': 'o1', 'OwnerId': 'AGENT_A', 'ContractID__c': 'c1', 'CreatedDate': '2023-04-02'},
                                   {'Id': 'o2', 'OwnerId': 'AGENT_B', 'ContractID__c': 'c2', 'CreatedDate': '2023-01-10'},
                                   {'Id': 'o3', 'OwnerId': 'AGENT_C', 'ContractID__c': 'c3', 'CreatedDate': '2023-03-01'}],
                   'Contract': [{'Id': 'c1', 'CompanySignedDate': '2023-06-01'}, {'Id': 'c2', 'CompanySignedDate': '2023-04-20'},
                                {'Id': 'c3', 'CompanySignedDate': '2023-04-15'}]},
        'expected': 'AGENT_C'}
Q_CARD = {'event_date_field': 'contract company-signed (closing) date', 'time_window': {'start': '2023-04-01', 'end': '2023-04-30', 'end_inclusive': True},
          'aggregate': 'average days from opportunity creation to company signed date per agent', 'ranking': {'metric': 'average days', 'direction': 'asc', 'limit': 1}}
S_CARD_CREATED = {'event_date_field': 'Opportunity.CreatedDate', 'time_window': {'start': '2023-04-01', 'end': '2023-05-01', 'end_inclusive': False},
                  'aggregate': 'average days from CreatedDate to CompanySignedDate per OwnerId', 'ranking': {'metric': 'avg_days', 'direction': 'asc', 'limit': 1}}
S_CARD_SIGNED = dict(S_CARD_CREATED, event_date_field='Contract.CompanySignedDate')


def main():
    t = Timer()
    db = str(dataset('crmarenapro') / 'sales_pipeline.duckdb')
    con = duckdb.connect(db, read_only=True)
    real = {'signed_date_sql': con.execute(SQL_SIGNED).fetchall(), 'created_date_sql': con.execute(SQL_CREATED).fetchall()}
    schema = schema_from_duckdb(db, tables=['Opportunity', 'Contract'])
    schema.dialect = 'sqlite'
    se = {name: synthetic_execution_verify(None, 'q12', sql, schema, cases=[CASE]) for name, sql in
          (('signed_date_sql', SQL_SIGNED_LITE), ('created_date_sql', SQL_CREATED_LITE))}
    cards = {'created_date_sql': compare_cards(None, Q_CARD, S_CARD_CREATED), 'signed_date_sql': compare_cards(None, Q_CARD, S_CARD_SIGNED)}
    out = {'real_data': real, 'synthetic_execution': {k: {'accept': v['accept'], 'reason': v['reason']} for k, v in se.items()},
           'intent_cards': {k: v['warnings'] for k, v in cards.items()}, 'seconds': t()}
    md = ['# crmarenapro q12 SQL verification (offline)', '', '| query | real DuckDB result (agent, avg days) | synthetic execution | intent-card warnings |', '|---|---|---|---|']
    for k in ('signed_date_sql', 'created_date_sql'):
        md.append(f"| {k} | {real[k]} | {'accept' if se[k]['accept'] else 'reject'} ({se[k]['reason']}) | {'; '.join(cards[k]['warnings']) or 'none'} |")
    md += ['', 'Expected agent (official ground truth): 005Wt000003NDEBIA4 (the signed-date reading).']
    save('crm_sql_verify', out, '\n'.join(md) + '\n'); print('\n'.join(md))


if __name__ == '__main__': main()
