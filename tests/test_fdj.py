"""FDJ: distances, canonicalisers, the paper's Fig. 6 scaffold example, the full join with an oracle."""
import math, random, re
import pytest
from dabcheck.fdj import distances as dist
from dabcheck.fdj.canonical import numeric_id, strip_decorations, ocr_fold, canonical_key, cve_candidates, canonical_name
from dabcheck.fdj.featurize import Featurization, FunctionExtractor, CodeExtractor, cost_to_cover, evaluate_and_pick_examples, distance_matrix
from dabcheck.fdj.cnf import Scaffold, best_thresholds, build_scaffold, cost_estimate, set_thresholds, adjusted_recall_target, adjusted_target_single, adjusted_target_high_dim, recall_and_fpr, recall_and_cost
from dabcheck.fdj.join import fdj_join, audit_join
from dabcheck.llm import MockLLM


def test_distances_basic():
    assert dist.d_exact('Abc', ' abc ') == 0 and dist.d_exact('a', 'b') == 1
    assert dist.d_exact(None, 'a') == math.inf
    assert dist.d_numeric_abs('1,500', 1495) == 5
    assert dist.d_date_days('2024-05-10', '2024-05-13 12:00:00') == 3.5
    assert dist.d_token_jaccard('get me bodied', 'Get Me Bodied!') == 0
    assert dist.d_char_edit('GetMe Bodied', 'Get Me Bodied') == pytest.approx(1 / 13)
    assert dist.d_digit_edit('tt0000042', 'InfT~~42') == 5  # leading zeros count as edits: that is why numeric_id exists
    assert dist.d_set_overlap(['a', 'b'], ['a']) == 0


def test_canonical():
    assert numeric_id('tt0000042') == 42 and numeric_id('nm001') == 1 and numeric_id('InfT~~7') == 7 and numeric_id(5) == 5
    assert numeric_id('Kw00002083') == 2083 and numeric_id('kwd..2905') == 2905
    assert strip_decorations('#001Wt00000PFj4zIAD ') == '001Wt00000PFj4zIAD'
    assert ocr_fold('naics-33G411', digits_only=True) == 'NA1C5336411' and ocr_fold('S1O2', digits_only=True) == '5102'
    assert ocr_fold('ks00002083') == ocr_fold('KS00002083') == 'K500002083'
    assert canonical_key('#AbC ') == 'abc' and canonical_key('tt0000042', numeric=True) == '42'
    assert cve_candidates('xref-CVE 2023 - 23397 :rawpfh') == ['2023-23397']
    assert cve_candidates('cve-2O19-1253') == ['2019-1253']
    assert canonical_name('RED ORANGE INTERNATIONAL, LLC.') == canonical_name('Red Orange International Limited')


FIG6 = {  # paper Fig. 6: five positives A-E, five negatives U-Z, four featurizations, integer distances
    'phi1': {'A': 1, 'B': 2, 'C': 3, 'D': 5, 'E': 8, 'U': 4, 'V': 7, 'W': 9, 'X': 6, 'Z': 0},
    'phi2': {'A': 2, 'B': 1, 'C': 9, 'D': 3, 'E': 4, 'U': 8, 'V': 1, 'W': 2, 'X': 9, 'Z': 7},
    'phi3': {'A': 9, 'B': 8, 'C': 1, 'D': 2, 'E': 1, 'U': 9, 'V': 8, 'W': 7, 'X': 6, 'Z': 9},
    'phi4': {'A': 5, 'B': 5, 'C': 5, 'D': 5, 'E': 5, 'U': 5, 'V': 5, 'W': 5, 'X': 5, 'Z': 5},
}
PAIRS = list('ABCDEUVWXZ'); LABELS = [1] * 5 + [0] * 5


def _D():
    return [[FIG6[f][p] for p in PAIRS] for f in ('phi1', 'phi2', 'phi3', 'phi4')]


def test_single_predicate_cost_matches_paper_example():
    # phi1 alone at T=0.8: theta=5 admits A,B,C,D plus negatives Z(0),U(4) -> FPR 2/6
    D = _D(); sc = Scaffold([[0]])
    th, cost = best_thresholds(sc, D, LABELS, 0.8)
    assert th == {0: 5} and cost == pytest.approx(2 / 6)


def test_scaffold_construction_prefers_useful_features_and_ignores_constant_one():
    D = _D(); log = []
    sc = build_scaffold(D, LABELS, 0.8, gamma=0.01, log=log)
    assert 3 not in sc.predicates()                  # phi4 is constant: never chosen
    assert cost_estimate(sc, D, LABELS, 0.8) <= cost_estimate(Scaffold([[0]]), D, LABELS, 0.8)
    r, fpr = recall_and_fpr(sc.evaluate(D), LABELS)
    assert r >= 0.8
    # the greedy conjunction step must add the single best feature first
    assert log[0]['step'] == 'conjunct' and log[0]['feature'] == min(range(3), key=lambda f: cost_estimate(Scaffold([[f]]), D, LABELS, 0.8))


def test_disjunction_can_reduce_cost():
    # positives split into two families only separable by phi1 OR phi3; conjunction cannot reach T=1
    D = [[0, 0, 9, 9, 5, 5, 9, 9], [9, 9, 0, 0, 9, 9, 5, 5]]
    labels = [1, 1, 1, 1, 0, 0, 0, 0]
    sc = build_scaffold(D, labels, 1.0, gamma=0.0)
    assert sc.clauses == [[0, 1]] or sc.clauses == [[1, 0]]
    assert recall_and_fpr(sc.evaluate(D), labels) == (1.0, 0.0)


def test_cost_to_cover_and_example_picking():
    D = _D()[:1]
    c = cost_to_cover(D, LABELS)
    assert c == [1, 1, 1, 2, 4]       # negatives with distance <= each positive under phi1
    ex = evaluate_and_pick_examples(D, LABELS, PAIRS, alpha=10, beta=4)
    assert ex == []                   # all costs < alpha -> nothing to improve
    ex = evaluate_and_pick_examples(D, LABELS, PAIRS, alpha=2, beta=4)
    assert ('E', 1) in ex and ('D', 1) in ex and all(y == 0 for p, y in ex if p in 'UVWXZ')


def test_adjusted_target_single_is_the_reference_binomial_bound():
    # reference get_single_thresh_target: smallest r/k with P(Bin(k, T) >= r) < delta
    import math
    k, T, d = 50, 0.9, 0.1
    tail = lambda r: sum(math.comb(k, i) * T ** i * (1 - T) ** (k - i) for i in range(r, k + 1))
    expected = next(r / k for r in range(int(math.ceil(T * k)), k + 1) if tail(r) < d)
    assert adjusted_target_single(k, T, d) == expected == 0.98
    assert 0.9 < adjusted_target_single(1000, 0.9, 0.1) < 0.92   # tightens with k
    assert adjusted_recall_target(0.9, 50, 0.1) == 0.98
    assert adjusted_recall_target(0.9, 10 ** 4, 0.1) < 0.91


def test_adjusted_target_high_dim_monte_carlo_is_above_T_and_cached():
    tp = adjusted_target_high_dim(40, 2000, 0.9, 2, 0.08, trials=200)
    assert tp == 0.0 or 0.9 < tp <= 1.0
    assert adjusted_recall_target(0.9, 40, 0.1, d=2, n_sampled=1000, n_total=10 ** 6, trials=200) > 0.9


def test_cost_modes():
    flags = [True, True, False, True, True, False]; labels = [1, 1, 1, 0, 0, 0]
    assert recall_and_cost(flags, labels, 'fpr') == (2 / 3, 2 / 4)      # paper: FP / (TP + FP)
    assert recall_and_cost(flags, labels, 'neg') == (2 / 3, 2 / 3)      # reference: FP / |S_n|


def test_code_extractor_is_restricted():
    ex = CodeExtractor("import re\ndef extract(record):\n    m = re.search(r'\\d+', str(record))\n    return int(m.group()) if m else None")
    assert ex('tt0042', 0) == 42
    with pytest.raises(ValueError):
        CodeExtractor("import os\ndef extract(record):\n    return os.listdir('.')")


def _noisy_ids(n, rng):
    """Synthetic DAB-like identifier tables: left ids 'tt%07d', right ids with random prefix/padding/leading zeros."""
    ids = rng.sample(range(1, 50000), n)
    left = [{'id': f'tt{v:07d}', 'name': f'title {v}'} for v in ids]
    right = []
    for v in ids:
        form = rng.choice([f'InfT~~{v}', f'Kw{v:08d}', f'kwd..{v}', f'{v}', f'#{v:05d}'])
        right.append({'ref': form, 'note': f'row for {v}'})
    rng.shuffle(right)
    truth = {(i, j) for i, l in enumerate(left) for j, r in enumerate(right) if numeric_id(l['id']) == numeric_id(r['ref'])}
    return left, right, truth


def test_fdj_join_with_oracle_meets_recall_and_precision():
    rng = random.Random(1)
    L, R, truth = _noisy_ids(60, rng)
    oracle = lambda l, r: int(numeric_id(l['id']) == numeric_id(r['ref']))
    feats = [Featurization('numeric_id', FunctionExtractor(lambda d: numeric_id(d['id'])), FunctionExtractor(lambda d: numeric_id(d['ref'])), 'numeric_abs'),
             Featurization('raw_edit', FunctionExtractor(lambda d: d['id']), FunctionExtractor(lambda d: d['ref']), 'char_edit'),
             Featurization('name_tokens', FunctionExtractor(lambda d: d['name']), FunctionExtractor(lambda d: d['note']), 'token_jaccard')]
    res = fdj_join(L, R, 'same entity', labeler=oracle, featurizations=feats, generate=False, T=0.9, delta=0.1,
                   min_train_pos=20, n_train_neg=200, batch=50, discovery_pos=10, discovery_neg=40, seed=1)
    found = set(res.matches)
    assert found <= truth                                   # precision 1 by refinement
    assert len(found) / len(truth) >= 0.9                   # recall target met
    assert 0 in res.scaffold.predicates()                    # the numeric id feature is selected
    assert res.n_refined <= len(res.candidates)
    assert res.n_pos_uniform >= 20 and res.n_sampled_uniform > 0 and res.target_feasible
    assert res.adjusted_target >= 0.9


def test_fdj_join_llm_generation_path_with_mock():
    """The generation loop is driven by a MockLLM that proposes a code extractor + distance."""
    rng = random.Random(2)
    L, R, truth = _noisy_ids(40, rng)
    oracle = lambda l, r: int(numeric_id(l['id']) == numeric_id(r['ref']))

    def handler(user, system, tag):
        if tag == 'fdj.walkthrough': return 'The join holds when both records carry the same embedded integer id.'
        if tag == 'fdj.descriptions':
            return '[{"name": "embedded_number", "description": "the integer embedded in the id", "left_feature": "digits of id", "right_feature": "digits of ref"}]'
        if tag.startswith('fdj.extractor'):
            side = 'id' if tag.endswith('left') else 'ref'
            return ('{"mode": "code", "code": "import re\\ndef extract(record):\\n    m = re.sub(r\'\\\\D\', \'\', str(record.get(\'' + side +
                    '\')))\\n    return int(m) if m else None"}')
        if tag == 'fdj.distance': return '{"distance": "numeric_abs"}'
        raise AssertionError(tag)
    llm = MockLLM(handler)
    res = fdj_join(L, R, 'same entity', llm, labeler=oracle, T=0.9, delta=0.1, min_train_pos=12, n_train_neg=150,
                   batch=40, discovery_pos=6, discovery_neg=30, seed=2, max_iter=2)
    assert set(res.matches) <= truth and len(res.matches) / len(truth) >= 0.9
    names = [f.name for f in res.featurizations]
    assert names[0] == 'raw_similarity' and 'embedded_number' in names      # reference seeds a similarity feature first
    tags = [e['tag'] for e in llm.log]
    assert tags.index('fdj.walkthrough') < tags.index('fdj.descriptions')    # discuss the examples before proposing
    assert 'fdj.extractor.left' in tags and 'fdj.extractor.right' in tags and 'fdj.distance' in tags


def test_audit_join_warns_on_leading_zeros_and_rule_swing():
    left = [f'kwd..{v}' for v in range(1, 300)]
    right = [f'Kw{v:08d}' for v in range(1, 300)] + ['Kw99999999'] * 3
    rep = audit_join(left, right, left_name='keyword.id', right_name='movie_keyword.keyword_id')
    assert rep['rules']['raw']['matched_keys'] == 0 and rep['rules']['numeric_id']['matched_keys'] == 299
    assert rep['best_rule'] == 'numeric_id'
    assert any('swings' in w for w in rep['warnings']) and any('zero-padded' in w for w in rep['warnings'])
    custom = audit_join(['1', '2'], ['1'], rules={'num': lambda v: v})            # custom rules without a 'raw' key
    assert custom['best_rule'] == 'num' and custom['rules']['num']['matched_keys'] == 1
