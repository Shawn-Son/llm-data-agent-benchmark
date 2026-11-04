"""DocETL-style extraction: number parsing, coverage warnings, operators, gleaning, resolve, optimizer."""
import json, re
import pytest
from dabcheck.extract.numbers import parse_number, parse_amount, find_numbers, words_to_number
from dabcheck.extract.coverage import ExtractSpec, CodeExtractor, coverage_report
from dabcheck.extract.ops import map_op, reduce_op, resolve, unnest, split, gather, render
from dabcheck.extract.gleaning import glean
from dabcheck.extract.pipeline import extract_values
from dabcheck.extract.optimizer import optimize_map
from dabcheck.llm import MockLLM


def test_amount_formats_from_usaspending_hint():
    assert parse_amount('1500000') == 1500000
    assert parse_amount('$1,500,000.00') == 1500000
    assert parse_amount('1.5M') == 1500000 and parse_amount('2.3B') == 2.3e9 and parse_amount('750K') == 750000
    assert parse_amount('USD 12,000') == 12000 and parse_amount('12000 USD') == 12000
    assert parse_amount('one million five hundred thousand dollars') == 1500000
    assert parse_amount('two hundred thirty-four thousand five hundred') == 234500
    assert parse_amount('$1,050,000 + $450,000') == 1500000
    assert parse_amount('five-figure') is None and parse_amount('low-to-mid millions') is None
    assert parse_amount('') is None and parse_amount(None) is None
    assert words_to_number('a hundred') == 100 and words_to_number('hello') is None


def test_find_numbers_handles_thousands_separators():
    found = find_numbers('The project has 30,522 forks and a stars count of 94931.')
    assert [v for v, _, _ in found] == [30522, 94931]


STARS = ExtractSpec('stars', patterns=[r'(?P<value>\d[\d,]*)\s+stars?\b', r'stars?\s+count\s+(?:of|is|:)\s*(?P<value>\d[\d,]*)',
                                       r'starred\s+(?P<value>\d[\d,]*)\s+times'], parse='int', min_coverage=0.95)
TEXTS = ['sveltejs/svelte has 73,499 stars and 4,091 forks', 'microsoft/typescript: a stars count of 94931',
         'lodash/lodash was starred 57,779 times', 'leaflet/leaflet 38715 stars', 'no numbers here', '']


def test_code_extractor_and_coverage_report():
    code = CodeExtractor(STARS)
    rows = [code(t) for t in TEXTS]
    assert [r['value'] for r in rows] == [73499, 94931, 57779, 38715, None, None]
    rep = coverage_report(TEXTS, rows, STARS)
    assert rep['parsed'] == 4 and rep['coverage'] == pytest.approx(4 / 6)
    assert any('coverage' in w for w in rep['warnings'])
    assert 'no numbers here' in rep['unparsed_samples']


def test_truncation_warning_for_naive_regex():
    naive = ExtractSpec('forks', patterns=[r'(?P<value>\d+)\s+forks'], parse='int')
    texts = ['30,522 forks', '7,201 forks', '955 forks']
    rows = [CodeExtractor(naive)(t) for t in texts]
    assert [r['value'] for r in rows] == [522, 201, 955]          # the DEPS_DEV_V1 failure reproduced
    rep = coverage_report(texts, rows, naive)
    assert rep['suspected_truncations'] == 2 and any('truncat' in w for w in rep['warnings'])


def test_extract_values_with_llm_fallback_and_evidence_check():
    texts = ['73,499 stars', 'This repo is admired by roughly ninety thousand developers (90,210 stargazers).', 'popular project']

    def handler(user, system, tag):
        if tag == 'extract.glean.init':
            if '90,210' in user: return '{"value": 90210, "evidence": "90,210 stargazers"}'
            return '{"value": 12345, "evidence": "not in text"}'    # hallucination: must be rejected
        if tag == 'extract.glean.validate': return '{"needs_refinement": false}'
        raise AssertionError(tag)
    llm = MockLLM(handler)
    res = extract_values(texts, STARS, llm, gleaning_rounds=1)
    assert res.values() == [73499, 90210, None]
    assert [r['source'] for r in res.rows] == ['code', 'llm', None]
    assert res.llm_rows == 2 and res.summary()['by_source'] == {'code': 1, 'llm': 1, None: 1}


def test_gleaning_refines_with_validator_feedback():
    doc = {'text': 'Officer X and Officer Y were present.'}
    responses = ['{"officers": ["X"]}',
                 '{"needs_refinement": true, "feedback": "Officer Y is missing"}',
                 '{"officers": ["X", "Y"]}',
                 '{"needs_refinement": false}']
    llm = MockLLM(responses=responses)
    out = glean(llm, doc, 'List officers in {{ input.text }}', {'officers': 'list of strings'}, validation_prompt='Are all officers listed?', max_rounds=2)
    assert out == {'officers': ['X', 'Y']}
    assert 'Officer Y is missing' in llm.log[2]['user']   # the refinement sees the validator feedback and history


def test_map_validation_retry_and_render():
    assert render('Name: {{ input.name }} / {{ input.meta.k }}', input={'name': 'a', 'meta': {'k': 1}}) == 'Name: a / 1'
    llm = MockLLM(responses=['{"n": -1}', '{"n": 3}'])
    out = map_op(llm, [{'t': 'x'}], 'Count in {{ input.t }}', {'n': 'integer'}, validations=[lambda d, o: isinstance(o.get('n'), int) and o['n'] >= 0])
    assert out == [{'t': 'x', 'n': 3}] and 'failed' in llm.log[1]['user']


def test_reduce_folds_batches_with_scratchpad():
    docs = [{'g': 'a', 'name': n} for n in ['x', 'y', 'x', 'z', 'y']]
    calls = []

    def handler(user, system, tag):
        calls.append(user)
        names = re.findall(r'"name": "(\w)"', user)
        pad = json.loads(user.split('scratchpad is: ')[1].split('\n\nReply')[0]) if 'scratchpad is:' in user else ''
        counts = json.loads(pad) if pad else {}
        for n in names: counts[n] = counts.get(n, 0) + 1
        return json.dumps({'repeated': sorted(k for k, v in counts.items() if v > 1), 'scratchpad': json.dumps(counts)})
    out = reduce_op(MockLLM(handler), docs, ['g'], 'Names mentioned more than once among {{ inputs }}', {'repeated': 'list'}, fold_batch=2)
    assert out == [{'g': 'a', 'repeated': ['x', 'y'], '_count': 5}] and len(calls) == 3


def test_resolve_merges_variants_with_and_without_llm():
    docs = [{'title': 'Get Me Bodied'}, {'title': 'GetMe Bodied'}, {'title': 'Get Me Bodied'}, {'title': 'Halo'}]
    out = resolve(None, docs, 'title')
    assert [d['title'] for d in out] == ['Get Me Bodied'] * 3 + ['Halo']
    llm = MockLLM(handler=lambda u, s, t: '{"same": false}' if t.endswith('compare') else '{"title": "x"}')
    docs2 = [{'title': 'Annual Street Maintenance 2021'}, {'title': 'Annual Street Maintenance 2022'}]
    out2 = resolve(llm, docs2, 'title', blocking_threshold=0.3)
    assert [d['title'] for d in out2] == ['Annual Street Maintenance 2021', 'Annual Street Maintenance 2022']
    llm2 = MockLLM(handler=lambda u, s, t: '{"same": true}' if t.endswith('compare') else '{"title": "Annual Street Maintenance"}')
    out3 = resolve(llm2, docs2, 'title', blocking_threshold=0.3)
    assert {d['title'] for d in out3} == {'Annual Street Maintenance'}


def test_split_gather_unnest():
    docs = [{'text': 'A' * 10 + '\n' + 'B' * 10 + '\n' + 'C' * 10}]
    chunks = split(docs, 'text', chunk_chars=12)
    assert [c['text_chunk'] for c in chunks] == ['A' * 10, '\n' + 'B' * 10, '\n' + 'C' * 10]
    g = gather(chunks, 'text', previous=1)
    assert g[1]['text_rendered'].startswith('<context_before>AAAAAAAAAA</context_before>\n<chunk>')
    assert unnest([{'d': 1, 'items': [{'k': 'a'}, {'k': 'b'}]}], 'items') == [{'d': 1, 'k': 'a'}, {'d': 1, 'k': 'b'}]


def test_optimizer_keeps_original_when_satisfactory_and_rewrites_otherwise():
    sample = [{'text': 'x'}]
    good = MockLLM(handler=lambda u, s, t: {'extract.opt.criteria': '{"criteria": ["complete"]}', 'extract.orig': '{"v": 1}',
                                            'extract.opt.rate': '{"rating": 5}'}[t])
    assert optimize_map(good, 'Get v from {{ input.text }}', {'v': 'int'}, sample)['plan'] == 'original'

    def handler(user, system, tag):
        if tag == 'extract.opt.criteria': return '{"criteria": ["complete"]}'
        if tag == 'extract.orig': return '{"v": 1}'
        if tag == 'extract.opt.rate': return '{"rating": 2}' if '"v": 1' in user else '{"rating": 5}'
        if tag.startswith('extract.opt.rewrite.chaining'):
            return '{"steps": [{"prompt": "step1 {{ input.text }}", "schema": {"tmp": "str"}}, {"prompt": "step2 {{ input.tmp }}", "schema": {"v": "int"}}]}'
        if tag.startswith('extract.opt.rewrite.isolating'): return '{"steps": []}'
        if tag in ('extract.chain0', 'extract.chain1'): return '{"tmp": "t", "v": 2}'
        if tag.startswith('extract.glean'): return '{"needs_refinement": false}' if 'validate' in tag else '{"v": 3}'
        if tag == 'extract.opt.pairwise': return '{"winner": "A"}' if 'Output A:\n{"v": 3}' in user else '{"winner": "B"}'
        raise AssertionError(tag)
    res = optimize_map(MockLLM(handler), 'Get v from {{ input.text }}', {'v': 'int'}, sample)
    assert res['plan'] in ('chaining', 'gleaning') and res['ratings']['original'] == 2
