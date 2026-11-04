"""SQL verification: schema loaders, synthetic execution, round trip, cohort cards, combination, selective."""
import json, sqlite3
import pytest
from dabcheck.sqlverify.schema import Schema, Table, Column, schema_from_ddl, schema_from_sqlite, render_schema
from dabcheck.sqlverify.synthexec import execute_sql, results_match, normalize_result, synthetic_execution_verify, synthesize_cases
from dabcheck.sqlverify.roundtrip import round_trip_verify
from dabcheck.sqlverify.cohort import compare_cards, cohort_check
from dabcheck.sqlverify.verify import verify_sql, selective
from dabcheck.llm import MockLLM

PGDUMP = '''
CREATE TABLE "title" (
    "id" character varying(64) NOT NULL,
    "title" text,
    "production_year" integer,
    "kind_id" integer
);
COPY "title" ("id", "title") FROM stdin;
tt0000042\tA film
\\.
CREATE TABLE public.kind_type (id integer, kind text);
'''


def test_schema_from_pg_dump_ddl():
    sc = schema_from_ddl(PGDUMP, 'postgres')
    assert set(sc.tables) == {'title', 'kind_type'}
    assert [c.name for c in sc.tables['title'].columns] == ['id', 'title', 'production_year', 'kind_id']
    assert sc.sqlite_type('character varying(64)') == 'TEXT' and sc.sqlite_type('integer') == 'INTEGER'
    assert 'TABLE title' in render_schema(sc)


def test_schema_from_sqlite(tmp_path):
    p = tmp_path / 'x.db'
    con = sqlite3.connect(p); con.execute('CREATE TABLE t (a INTEGER, b TEXT)'); con.execute("INSERT INTO t VALUES (1, 'x')"); con.commit(); con.close()
    sc = schema_from_sqlite(str(p))
    assert sc.tables['t'].column_names() == ['a', 'b'] and sc.tables['t'].samples == [{'a': '1', 'b': 'x'}]


# A crmarenapro-q12-like schema: opportunities and contracts; the question anchors April on the signing date.
CRM = Schema(dialect='duckdb').add(Table('Opportunity', [Column('Id', 'text'), Column('OwnerId', 'text'), Column('ContractID__c', 'text'), Column('CreatedDate', 'date')])) \
                              .add(Table('Contract', [Column('Id', 'text'), Column('CompanySignedDate', 'date')]))
SQL_RIGHT = '''SELECT o.OwnerId, AVG(julianday(c.CompanySignedDate) - julianday(o.CreatedDate)) AS d
FROM Opportunity o JOIN Contract c ON c.Id = o.ContractID__c
WHERE c.CompanySignedDate >= '2023-04-01' AND c.CompanySignedDate < '2023-05-01' GROUP BY o.OwnerId ORDER BY d LIMIT 1'''
SQL_WRONG = SQL_RIGHT.replace("c.CompanySignedDate >= '2023-04-01' AND c.CompanySignedDate < '2023-05-01'",
                              "o.CreatedDate >= '2023-04-01' AND o.CreatedDate < '2023-05-01'")
CASE = {'tables': {'Opportunity': [{'Id': 'o1', 'OwnerId': 'A', 'ContractID__c': 'c1', 'CreatedDate': '2023-04-02'},   # created April, signed June
                                   {'Id': 'o2', 'OwnerId': 'B', 'ContractID__c': 'c2', 'CreatedDate': '2023-01-10'},   # created Jan, signed April (300 days)
                                   {'Id': 'o3', 'OwnerId': 'C', 'ContractID__c': 'c3', 'CreatedDate': '2023-03-01'}],  # created Mar, signed April (45 days)
                   'Contract': [{'Id': 'c1', 'CompanySignedDate': '2023-06-01'}, {'Id': 'c2', 'CompanySignedDate': '2023-04-20'},
                                {'Id': 'c3', 'CompanySignedDate': '2023-04-15'}]},
        'expected': 'C', 'note': 'month anchored on signing date', 'mode': 'answer_first'}


def test_execute_and_match():
    ex = execute_sql(CRM, CASE['tables'], SQL_RIGHT)
    assert 'error' not in ex and ex['rows'][0][0] == 'C'
    assert results_match('C', ex['rows'])            # scalar expected vs (owner, days) row: projection match
    ex2 = execute_sql(CRM, CASE['tables'], SQL_WRONG)
    assert ex2['rows'][0][0] == 'A' and not results_match('C', ex2['rows'])
    assert normalize_result([[1, 'B'], [2.0, 'a']]) == normalize_result([['2', 'A'], [1.0, 'b']])
    assert results_match([[1, 'x']], [(1.0, 'X')]) and not results_match(3, [(4,)])
    assert 'error' in execute_sql(CRM, {}, 'SELECT * FROM nope')


def test_synthetic_execution_separates_right_and_wrong_sql():
    gen = MockLLM(handler=lambda u, s, t: json.dumps({'cases': [CASE]}))
    assert synthetic_execution_verify(gen, 'q', SQL_RIGHT, CRM, n_cases=1)['accept'] is True
    r = synthetic_execution_verify(gen, 'q', SQL_WRONG, CRM, n_cases=1)
    assert r['accept'] is False and r['n_failed'] == 1
    # the candidate SQL must not leak into the generator prompt (independence of the verifier)
    assert all('CompanySignedDate >=' not in e['user'] for e in gen.log)
    assert synthesize_cases(MockLLM(responses=['{"cases": [{"bad": 1}]}']), 'q', CRM) == []


def test_round_trip_threshold():
    llm = MockLLM(responses=['{"question": "Which owner had the shortest average cycle for opportunities created in April 2023?"}',
                             '{"differences": ["period anchored on creation date instead of signing date"], "score": 2}'])
    r = round_trip_verify(llm, 'quickest turnaround ... closed in April 2023', SQL_WRONG, CRM, tau=4)
    assert r['accept'] is False and r['score'] == 2 and 'anchored' in r['reason']
    assert 'quickest turnaround' not in llm.log[0]['user']   # back-translation is isolated from the question
    ok = MockLLM(responses=['{"question": "..."}', '{"differences": [], "score": 5}'])
    assert round_trip_verify(ok, 'q', SQL_RIGHT, CRM)['accept'] is True


def test_compare_cards_deterministic_time_checks():
    q = {'event_date_field': 'contract signing date', 'time_window': {'start': '2023-04-01', 'end': '2023-04-30', 'end_inclusive': True},
         'as_of_logic': 'latest report on or before the grant date', 'ranking': {'limit': 1}}
    s = {'event_date_field': 'Opportunity.CreatedDate', 'time_window': {'start': '2023-04-01', 'end': '2023-05-01', 'end_inclusive': False},
         'as_of_logic': None, 'ranking': {'limit': 1}}
    w = compare_cards(None, q, s)['warnings']
    assert any('date field' in x for x in w) and any('as-of' in x for x in w)
    assert not any('time window end differs' in x for x in w)    # 2023-04-30 inclusive == 2023-05-01 exclusive
    s2 = dict(s, time_window={'start': '2021-06-01', 'end': '2022-06-01', 'end_inclusive': False}, event_date_field='contract signing date', as_of_logic='x')
    q2 = dict(q, time_window={'start': '2021-06-01', 'end': '2022-06-01', 'end_inclusive': True})
    assert any('end differs' in x for x in compare_cards(None, q2, s2)['warnings'])   # the civic q4 inclusive-end trap
    same = {'event_date_field': 'Contract.CompanySignedDate', 'time_window': q['time_window'], 'as_of_logic': 'x', 'ranking': {'limit': 1}}
    assert not any('date field' in x for x in compare_cards(None, dict(q, event_date_field='contract company-signed (closing) date'), same)['warnings'])


def test_cohort_check_with_llm_judgement():
    def handler(user, system, tag):
        if tag.endswith('card.question'):
            return json.dumps({'population': 'all female BRCA patients with known histology', 'denominator': 'all such patients',
                               'time_window': None, 'event_date_field': None, 'ranking': None})
        if tag.endswith('card.sql'):
            return json.dumps({'population': 'female BRCA patients with at least one PASS mutation row', 'denominator': 'profiled patients',
                               'time_window': None, 'event_date_field': None, 'ranking': None})
        if tag.endswith('compare'):
            return json.dumps({'fields': {'population': {'verdict': 'narrower', 'evidence': 'restricted to mutation-profiled patients'},
                                          'aggregate': {'verdict': 'same', 'evidence': ''}}})
        raise AssertionError(tag)
    r = cohort_check(MockLLM(handler), 'chi-square ...', 'SELECT ...', CRM)
    assert r['accept'] is False and 'population: SQL is narrower' in r['warnings'][0]


def test_verify_combination_and_selective():
    gen = MockLLM(handler=lambda u, s, t: json.dumps({'cases': [CASE]}) if t.startswith('sqlverify.se') else
                  ('{"question": "x"}' if t == 'sqlverify.rt.back' else '{"differences": [], "score": 5}'))
    r = verify_sql(gen, 'q', SQL_WRONG, CRM, methods=('rt', 'se'), combine='and')
    assert r['accept'] is False and r['methods']['rt']['accept'] and not r['methods']['se']['accept']
    assert verify_sql(gen, 'q', SQL_WRONG, CRM, methods=('rt', 'se'), combine='or')['accept'] is True
    out = selective(lambda q: SQL_WRONG, gen, 'q', CRM, methods=('se',))
    assert out['abstained'] is True and out['sql'] is None
    out2 = selective(lambda q: SQL_RIGHT, gen, 'q', CRM, methods=('se',))
    assert out2['abstained'] is False and out2['sql'] == SQL_RIGHT


def test_ordered_comparison_follows_order_by():
    from dabcheck.sqlverify.synthexec import has_order_by
    assert has_order_by('SELECT a FROM t ORDER BY a') and not has_order_by('SELECT a FROM t')
    assert results_match([[1, 'a'], [2, 'b']], [(2, 'b'), (1, 'a')], ordered=False)
    assert not results_match([[1, 'a'], [2, 'b']], [(2, 'b'), (1, 'a')], ordered=True)   # ORDER BY: row order matters
    assert results_match([[1, 'a'], [2, 'b']], [('a', 1), ('b', 2)], ordered=True)       # column order does not
