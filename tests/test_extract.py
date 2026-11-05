"""DocETL-style extraction: number parsing, coverage warnings, operators, gleaning, resolve, optimizer."""
import json, re
import pytest
from dabcheck.extract.numbers import parse_number, parse_amount, find_numbers, words_to_number
from dabcheck.extract.coverage import ExtractSpec, CodeExtractor, coverage_report
from dabcheck.extract.ops import map_op, parallel_map, reduce_op, resolve, unnest, split, gather, render, validate_output_types
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
    assert parse_amount('5 million') == 5e6 and parse_amount('revenue of 5 million') == 5e6
    assert parse_amount('five-figure') is None and parse_amount('low-to-mid millions') is None
    assert parse_amount('') is None and parse_amount(None) is None
    # prose with a stray number word is vague, not an amount (usaspending amount_text, Nov 2026 run)
    assert parse_amount('For ASRC Federal Professional Services, LLC, the Department of Defense has allocated a not insignificant million-dollar tier') is None
    assert parse_amount('In terms of federal contracting scope, this allocation to FOUR POINTS TECHNOLOGY, L.L.C. falls in a modest band') is None
    assert parse_amount('one million plus two hundred thousand dollars') == 1200000
    assert words_to_number('a hundred') == 100 and words_to_number('hello') is None
    assert parse_number('100 m') == 100 and parse_number('5 t') == 5          # units, not scales
    assert parse_number('7,201,') == 7201


def test_find_numbers_handles_thousands_separators():
    found = find_numbers('The project has 30,522 forks and a stars count of 94931.')
    assert [v for v, _, _ in found] == [30522, 94931]
    assert [v for v, _, _ in find_numbers('about 5 million users')] == [5e6]


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
    texts = ['73,499 stars', 'This repo is admired by roughly ninety thousand developers (90,210 stargazers).', 'popular project', 'nice']

    def handler(user, system, tag):
        if tag == 'extract.glean.init':
            if '90,210' in user: return '{"value": 90210, "evidence": "90,210 stargazers"}'
            if 'nice' in user: return '{"value": true, "evidence": "nice"}'          # a boolean is not a value
            return '{"value": "12345", "evidence": "not in text"}'                     # hallucination: must be rejected
        if tag == 'extract.glean.validate': return '{"should_refine": false, "improvements": ""}'
        raise AssertionError(tag)
    llm = MockLLM(handler)
    res = extract_values(texts, STARS, llm, gleaning_rounds=1)
    assert res.values() == [73499, 90210, None, None]
    assert [r['source'] for r in res.rows] == ['code', 'llm', None, None]
    assert res.llm_rows == 3 and res.summary()['by_source'] == {'code': 1, 'llm': 1, None: 2}


def test_gleaning_keeps_history_and_uses_validator_feedback():
    doc = {'text': 'Officer X and Officer Y were present.'}
    responses = ['{"officers": ["X"]}',
                 '{"should_refine": true, "improvements": "Officer Y is missing"}',
                 '{"officers": ["X", "Y"]}',
                 '{"should_refine": false, "improvements": ""}']
    llm = MockLLM(responses=responses)
    out = glean(llm, doc, 'List officers in {{ input.text }}', {'officers': 'list of strings'}, validation_prompt='Are all officers listed?', max_rounds=2)
    assert out == {'officers': ['X', 'Y']}
    validator_call, refine_call = llm.log[1], llm.log[2]
    roles = [m['role'] for m in validator_call['messages']]
    assert roles == ['user', 'assistant', 'user'] and '["X"]' in validator_call['messages'][1]['content']   # validator sees prompt + previous answer
    assert [m['role'] for m in refine_call['messages']] == ['user', 'assistant', 'user']
    assert 'Officer Y is missing' in refine_call['messages'][-1]['content'] and 'List officers' in refine_call['messages'][0]['content']
    # a malformed validator verdict is asked again, then treated as "no refinement"
    llm2 = MockLLM(responses=['{"officers": ["X"]}', 'not json', 'still not json'])
    assert glean(llm2, doc, 'List officers in {{ input.text }}', {'officers': 'list'}, validation_prompt='v', max_rounds=1) == {'officers': ['X']}


def test_map_validation_retry_history_and_drop():
    assert render('Name: {{ input.name }} / {{ input.meta.k }}', input={'name': 'a', 'meta': {'k': 1}}) == 'Name: a / 1'
    assert validate_output_types({'n': 3}, {'n': 'integer'}) is None
    assert validate_output_types({'n': 'x'}, {'n': 'integer'}) and validate_output_types({}, {'n': 'integer'}) and validate_output_types([1], {'n': 'int'})
    llm = MockLLM(responses=['{"n": -1}', '{"n": 3}'])
    out = map_op(llm, [{'t': 'x'}], 'Count in {{ input.t }}', {'n': 'integer'}, validations=[lambda d, o: isinstance(o.get('n'), int) and o['n'] >= 0])
    assert out == [{'t': 'x', 'n': 3}]
    msgs = llm.log[1]['messages']
    assert [m['role'] for m in msgs] == ['user', 'assistant', 'user'] and '{"n": -1}' in msgs[1]['content'] and 'failed validation' in msgs[2]['content']
    # exhausted retries drop the document (DocETL) instead of keeping an invalid output
    llm = MockLLM(responses=['{"n": -1}', '{"n": -2}', '{"n": -3}'])
    assert map_op(llm, [{'t': 'x'}], 'Count in {{ input.t }}', {'n': 'integer'}, validations=[lambda d, o: o['n'] >= 0]) == []
    # a list reply is a type failure, retried, then dropped
    llm = MockLLM(responses=['[{"n": 3}]', '"3"', 'nope'])
    assert map_op(llm, [{'t': 'x'}], 'Count in {{ input.t }}', {'n': 'integer'}) == []
    # parallel_map: every prompt sees the original document only
    llm = MockLLM(handler=lambda u, s, t: '{"a": 1}' if t.endswith('pmap0') else ('{"b": "seen a" if "a" in u else "fresh"}'.replace('"seen a" if "a" in u else "fresh"', '"' + ('seen' if '"a": 1' in u else 'fresh') + '"')))
    out = parallel_map(llm, [{'t': 'x'}], [('P0 {{ input.t }}', {'a': 'int'}), ('P1 {{ input.t }} {{ input.a }}', {'b': 'str'})], tag='ignored')
    assert out == [{'t': 'x', 'a': 1, 'b': 'fresh'}]


def test_reduce_folds_batches_with_scratchpad_and_fold_prompt_contract():
    docs = [{'g': 'a', 'name': n} for n in ['x', 'y', 'x', 'z', 'y']]
    calls = []

    def handler(user, system, tag):
        calls.append(user)
        names = re.findall(r'"name": "(\w)"', user)
        pad = json.loads(user.split('Current scratchpad: ')[1].split('\n\nReply')[0]) if 'Current scratchpad: ' in user else None
        counts = json.loads(pad) if pad else {}
        for n in names: counts[n] = counts.get(n, 0) + 1
        return json.dumps({'repeated': sorted(k for k, v in counts.items() if v > 1), 'updated_scratchpad': json.dumps(counts)})
    out = reduce_op(MockLLM(handler), docs, ['g'], 'Names mentioned more than once among {{ inputs }}', {'repeated': 'list'}, fold_batch=2)
    assert out == [{'g': 'a', 'repeated': ['x', 'y'], '_count': 5}] and len(calls) == 3
    assert 'Current scratchpad: null' in calls[0]                 # first fold: nothing tracked yet
    # a DocETL-style fold_prompt references {{ output }}; a group that fits one batch is not folded
    seen = []
    llm = MockLLM(handler=lambda u, s, t: (seen.append(u), '{"total": 7}')[1])
    out = reduce_op(llm, docs, ['g'], 'Sum {{ inputs }}', {'total': 'int'}, fold_prompt='Prev: {{ output.total }} / New: {{ inputs }}', fold_batch=3)
    assert out[0]['total'] == 7 and 'Prev: 7 / New:' in seen[1]
    seen.clear()
    reduce_op(llm, docs, ['g'], 'Sum {{ inputs }}', {'total': 'int'}, fold_batch=10)
    assert len(seen) == 1 and 'scratchpad' not in seen[0]
    # list-valued reduce keys
    assert reduce_op(llm, [{'tags': ['b', 'a'], 'v': 1}, {'tags': ['a', 'b'], 'v': 2}], ['tags'], 'Sum {{ inputs }}', {'total': 'int'})[0]['_count'] == 2


def test_resolve_blocking_comparison_and_canonical_values():
    docs = [{'title': 'Get Me Bodied'}, {'title': 'GetMe Bodied'}, {'title': 'Get Me Bodied'}, {'title': 'Halo'}]
    out = resolve(None, docs, 'title')
    assert [d['title'] for d in out] == ['Get Me Bodied'] * 3 + ['Halo']
    # a substring pair is a candidate, not a match: the comparison prompt decides
    llm = MockLLM(handler=lambda u, s, t: '{"same": false}' if t.endswith('compare') else '{"title": "x"}')
    docs2 = [{'title': 'Halo'}, {'title': 'Halo 2'}, {'title': 'Annual Street Maintenance 2021'}, {'title': 'Annual Street Maintenance 2022'}]
    out2 = resolve(llm, docs2, 'title', blocking_threshold=0.3)
    assert [d['title'] for d in out2] == ['Halo', 'Halo 2', 'Annual Street Maintenance 2021', 'Annual Street Maintenance 2022']
    assert sum(1 for e in llm.log if e['tag'].endswith('compare')) == 2
    llm2 = MockLLM(handler=lambda u, s, t: '{"same": true}' if t.endswith('compare') else '{"title": "Annual Street Maintenance"}')
    out3 = resolve(llm2, docs2[2:], 'title', blocking_threshold=0.3)
    assert {d['title'] for d in out3} == {'Annual Street Maintenance'} and out3[0]['title_original'] == 'Annual Street Maintenance 2021'
    # singletons keep their original value and type; blocking conditions prune pairs
    assert [d['id'] for d in resolve(None, [{'id': 5}, {'id': 5}, {'id': 7}], 'id')] == [5, 5, 7]
    out4 = resolve(None, [{'t': 'a b', 'y': 1}, {'t': 'a b c', 'y': 2}], 't', blocking_conditions=[lambda p, q: p['y'] == q['y']])
    assert [d['t'] for d in out4] == ['a b', 'a b c']


def test_split_gather_unnest():
    docs = [{'text': 'A' * 10 + '\n' + 'B' * 10 + '\n' + 'C' * 10}]
    chunks = split(docs, 'text', chunk_chars=12)
    assert [c['text_chunk'] for c in chunks] == ['A' * 10, '\n' + 'B' * 10, '\n' + 'C' * 10]
    g = gather(chunks, 'text', previous=1)
    assert g[1]['text_rendered'].startswith('<context_before>AAAAAAAAAA</context_before>\n<chunk>')
    g2 = gather(chunks, 'text', previous=1, summary_key='summary')           # missing summaries fall back to the chunk text
    assert '<context_before>AAAAAAAAAA</context_before>' in g2[1]['text_rendered']
    assert unnest([{'d': 1, 'items': [{'k': 'a'}, {'k': 'b'}]}], 'items') == [{'d': 1, 'k': 'a'}, {'d': 1, 'k': 'b'}]


def test_optimizer_gate_rewrites_and_pairwise_selection():
    sample = [{'text': 'x'}, {'text': 'y'}]
    good = MockLLM(handler=lambda u, s, t: {'extract.opt.criteria': '{"criteria": ["complete"]}', 'extract.orig': '{"v": 1}',
                                            'extract.opt.assess': '{"needs_improvement": false, "reasons": []}'}[t])
    res = optimize_map(good, 'Get v from {{ input.text }}', {'v': 'int'}, sample)
    assert res['plan'] == 'original' and not any(e['tag'] == 'extract.opt.rate' for e in good.log)
    assert 'Sample output' in next(e['user'] for e in good.log if e['tag'] == 'extract.opt.criteria')   # criteria see outputs

    def handler(user, system, tag):
        if tag == 'extract.opt.criteria': return '{"criteria": ["complete"]}'
        if tag == 'extract.orig': return '{"v": 1}'
        if tag == 'extract.opt.assess': return '{"needs_improvement": true, "reasons": ["misses values"]}'
        if tag == 'extract.opt.rate': return '{"rating": 2}' if '"v": 1' in user else '{"rating": 5}'
        if tag.startswith('extract.opt.rewrite.chaining'):
            return '{"steps": [{"prompt": "step1 {{ input.text }}", "output_keys": ["tmp"]}, {"prompt": "step2 {{ input.tmp }}", "output_keys": ["v"]}]}'
        if tag.startswith('extract.opt.rewrite.isolating'): return '{"steps": []}'
        if tag in ('extract.chain0', 'extract.chain1'): return '{"tmp": "t", "v": 2}'
        if tag.startswith('extract.glean'): return '{"should_refine": false, "improvements": ""}' if 'validate' in tag else '{"v": 3}'
        if tag == 'extract.opt.pairwise': return '{"winner": "A"}' if 'Output A:\n{"v": 3}' in user else ('{"winner": "B"}' if 'Output B:\n{"v": 3}' in user else '{"winner": "tie"}')
        raise AssertionError(tag)
    res = optimize_map(MockLLM(handler), 'Get v from {{ input.text }}', {'v': 'int'}, sample)
    assert res['plan'] == 'gleaning' and res['ratings']['original'] == 2
    assert res['wins']['gleaning'] == 2 and res['wins']['chaining'] <= 1          # one win per pair, not per document
