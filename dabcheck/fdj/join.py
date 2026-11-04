"""FDJ end-to-end (paper Alg. 5; reference fdj/create_fd/get_join_features.py + utils/prep_data.py)
and the LLM-free join audit."""
from __future__ import annotations
import math, random, re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from .featurize import Featurization, FunctionExtractor, Pair, distance_matrix, get_candidate_featurizations
from .cnf import Scaffold, build_scaffold, set_thresholds, recall_and_cost
from .canonical import canonical_key
from ..llm import BaseLLM

Labeler = Callable[[Any, Any], int]   # L_p(l, r) -> 0/1


def llm_labeler(llm: BaseLLM, predicate: str, model: Optional[str] = None) -> Labeler:
    """The join LLM L_p (reference join_prompt_with_val: the predicate plus both values, Yes/No)."""
    def label(l, r) -> int:
        user = (f'{predicate}\n\nLEFT record:\n{str(l)[:4000]}\n\nRIGHT record:\n{str(r)[:4000]}\n\n'
                'Does the join condition hold for this pair? Reply with JSON: {"match": true|false}')
        out = llm.json(user, model=model or getattr(llm, 'cheap_model', None), max_tokens=200, tag='fdj.label')
        return int(bool(out.get('match'))) if isinstance(out, dict) else 0
    return label


def raw_similarity_featurization() -> Featurization:
    """Stand-in for the reference's initial `sem_sim` featurization (embedding cosine similarity
    of the raw values): token Jaccard distance of the records' text. Register an embedding
    distance with `distances.register_distance` to use embeddings instead."""
    return Featurization('raw_similarity', FunctionExtractor(lambda d: str(d), 'raw.left'),
                         FunctionExtractor(lambda d: str(d), 'raw.right'), 'token_jaccard', 'token overlap of the raw records')


@dataclass
class FDJResult:
    matches: List[Pair]
    candidates: List[Pair]
    featurizations: List[Featurization]
    scaffold: Scaffold
    adjusted_target: float
    n_labeled: int
    n_refined: int
    sample_recall: float
    target_feasible: bool = True   # False: no thresholds reached the adjusted target on the threshold sample
    n_sampled_uniform: int = 0      # uniformly sampled pairs labelled (for the positive-rate estimate)
    n_pos_uniform: int = 0
    log: list = field(default_factory=list)

    def summary(self) -> Dict[str, Any]:
        return {'matches': len(self.matches), 'candidates': len(self.candidates),
                'decomposition': self.scaffold.describe(self.featurizations), 'adjusted_target': self.adjusted_target,
                'labeled_pairs': self.n_labeled, 'llm_refinement_calls': self.n_refined, 'sample_recall': self.sample_recall,
                'target_feasible': self.target_feasible, 'uniform_sample': {'pairs': self.n_sampled_uniform, 'positives': self.n_pos_uniform}}


def sample_training_pairs(L, R, labeler: Labeler, *, min_train_pos: int, n_train_neg: int, batch: int, rng: random.Random,
                          max_uniform: Optional[int] = None, candidates_fn: Optional[Callable[[], Sequence[Pair]]] = None,
                          label_random_negatives: bool = True) -> Dict[str, Any]:
    """Reference prep_data.get_suffiecient_positives + get_train_with_negatives.

    Pairs are drawn uniformly without replacement in batches of `batch` and labelled until
    `min_train_pos` positives are found (or `max_uniform` pairs were labelled). Negatives are the
    labelled negatives plus random extra pairs up to `n_train_neg`; the reference assumes those
    extra pairs negative without labelling them (label_random_negatives=False), the paper labels
    everything (default). When the uniform budget runs out and `candidates_fn` is given, the
    positives are topped up from that generator (a deviation for very sparse joins, logged).
    """
    nL, nR = len(L), len(R); total = nL * nR
    labels: Dict[Pair, int] = {}; seen = set(); n_uniform = 0; n_pos_uniform = 0; topped_up = 0
    cap = total if max_uniform is None else min(total, max_uniform)
    while n_pos_uniform < min_train_pos and len(seen) < cap:
        want = min(batch, cap - len(seen))
        drawn = 0
        while drawn < want and len(seen) < total:
            p = (rng.randrange(nL), rng.randrange(nR))
            if p in seen: continue
            seen.add(p); y = labeler(L[p[0]], R[p[1]]); labels[p] = y; drawn += 1; n_uniform += 1; n_pos_uniform += y
    if n_pos_uniform < min_train_pos and candidates_fn is not None:
        extra = [p for p in candidates_fn() if p not in labels]; rng.shuffle(extra)
        for p in extra:
            if sum(labels.values()) >= min_train_pos: break
            labels[p] = labeler(L[p[0]], R[p[1]]); topped_up += 1
    positives = [p for p, y in labels.items() if y]
    negatives = [p for p, y in labels.items() if not y]
    attempts = 0
    while len(negatives) < n_train_neg and attempts < 10 * n_train_neg and len(labels) < total:
        p = (rng.randrange(nL), rng.randrange(nR)); attempts += 1
        if p in labels: continue
        if label_random_negatives:
            y = labeler(L[p[0]], R[p[1]]); labels[p] = y
            if y: positives.append(p)
            else: negatives.append(p)
        else:
            labels[p] = 0; negatives.append(p)
    rng.shuffle(positives); rng.shuffle(negatives)
    return {'positives': positives, 'negatives': negatives[:n_train_neg], 'labels': labels, 'n_uniform': n_uniform,
            'n_pos_uniform': n_pos_uniform, 'topped_up': topped_up, 'n_labeled': len(labels) if label_random_negatives else n_uniform + topped_up}


def evaluate_pairs(feats: Sequence[Featurization], scaffold: Scaffold, L, R, block_on: Optional[int] = None) -> List[Pair]:
    """All (i, j) with Pi(l, r) = 1. Features are extracted once per record (linear cost);
    a predicate with threshold 0 on an `exact` distance is used as a hash-join block."""
    nL, nR = len(L), len(R)
    exact_block = None
    for f in scaffold.predicates():
        if feats[f].distance == 'exact' and scaffold.thresholds.get(f, 1) <= 0 and any(f in c and len(c) == 1 for c in scaffold.clauses):
            exact_block = f; break
    if block_on is not None: exact_block = block_on
    out = []
    if exact_block is not None:
        f = feats[exact_block]; index = defaultdict(list)
        for j in range(nR):
            v = f.right(R[j], j)
            if v not in (None, ''): index[str(v).strip().lower()].append(j)
        for i in range(nL):
            v = f.left(L[i], i)
            if v in (None, ''): continue
            for j in index.get(str(v).strip().lower(), []):
                if _holds(feats, scaffold, L, R, i, j): out.append((i, j))
        return out
    for i in range(nL):
        for j in range(nR):
            if _holds(feats, scaffold, L, R, i, j): out.append((i, j))
    return out


def _holds(feats, scaffold, L, R, i, j) -> bool:
    for clause in scaffold.clauses:
        if not any(feats[f](L[i], R[j], i, j) <= scaffold.thresholds.get(f, -math.inf) for f in clause): return False
    return True


def fdj_join(L: Sequence[Any], R: Sequence[Any], predicate: str, llm: Optional[BaseLLM] = None, *,
             labeler: Optional[Labeler] = None, T: float = 0.9, delta: float = 0.1,
             min_train_pos: int = 250, n_train_neg: int = 1500, batch: int = 100, max_uniform: Optional[int] = None,
             discovery_pos: int = 50, discovery_neg: int = 100, n_examples: int = 5,
             featurizations: Optional[Sequence[Featurization]] = None, generate: bool = True,
             max_iter: int = 4, alpha: int = 10, beta: int = 10, gamma: float = 0.1, cost_mode: str = 'fpr',
             seed: int = 0, candidates_fn: Optional[Callable[[], Sequence[Pair]]] = None, refine: bool = True,
             label_random_negatives: bool = True, mc_trials: int = 1000, model: Optional[str] = None) -> FDJResult:
    """Approximate semantic join with recall target T and failure probability delta (Alg. 5).

    Sampling and splits follow the reference implementation: uniform pairs are labelled until
    `min_train_pos` positives exist (reference 250), negatives are completed to `n_train_neg`
    (1500); the first `discovery_pos` positives and `discovery_neg` negatives (50 / 100) drive
    featurization generation and the scaffold, the rest set the thresholds at the adjusted target.
    `labeler` is L_p (defaults to the LLM with `predicate`); `featurizations` seeds the candidate
    set; generate=False uses only the seeds (no LLM needed).
    """
    rng = random.Random(seed)
    if labeler is None:
        if llm is None: raise ValueError('need an llm or a labeler')
        labeler = llm_labeler(llm, predicate, model)
    log: list = []
    nL, nR = len(L), len(R)
    s = sample_training_pairs(L, R, labeler, min_train_pos=min_train_pos, n_train_neg=n_train_neg, batch=batch, rng=rng,
                              max_uniform=max_uniform, candidates_fn=candidates_fn, label_random_negatives=label_random_negatives)
    if s['topped_up']: log.append({'step': 'sample', 'note': f"{s['topped_up']} positives supplied by candidates_fn (uniform sample too sparse)"})
    pos, neg = s['positives'], s['negatives']
    disc_pairs = pos[:discovery_pos] + neg[:discovery_neg]; disc_labels = [1] * len(pos[:discovery_pos]) + [0] * len(neg[:discovery_neg])
    thr_pairs = pos[discovery_pos:] + neg[discovery_neg:]; thr_labels = [1] * len(pos[discovery_pos:]) + [0] * len(neg[discovery_neg:])
    if not any(thr_labels):   # too few positives to hold a threshold split: reuse the discovery sample (logged)
        thr_pairs, thr_labels = disc_pairs, disc_labels; log.append({'step': 'sample', 'note': 'threshold sample reuses the discovery sample'})
    # candidate featurizations (Alg. 1-3) on the discovery sample
    feats = list(featurizations or [])
    if generate:
        if llm is None: raise ValueError('generate=True needs an llm')
        if not feats: feats = [raw_similarity_featurization()]
        feats = get_candidate_featurizations(llm, L, R, disc_pairs, disc_labels, predicate, seed=feats, max_iter=max_iter,
                                             alpha=alpha, beta=beta, n_examples=n_examples, model=model, rng=rng, log=log)
    if not feats: raise ValueError('no featurizations available')
    D = distance_matrix(feats, L, R, disc_pairs)
    # scaffold (Alg. 4) on the discovery sample
    scaffold = build_scaffold(D, disc_labels, T, gamma=gamma, log=log, cost_mode=cost_mode)
    # thresholds at the adjusted target on the threshold sample (Sec. 6.3)
    D2 = distance_matrix(feats, L, R, thr_pairs)
    scaffold, Tp, feasible = set_thresholds(scaffold, D2, thr_labels, T, delta, cost_mode=cost_mode,
                                            n_sampled=s['n_uniform'] or None, n_total=nL * nR, trials=mc_trials)
    sample_recall = recall_and_cost(scaffold.evaluate(D2), thr_labels)[0]
    # candidate result and refinement with L_p (precision 1)
    candidates = evaluate_pairs(feats, scaffold, L, R)
    known = s['labels']
    matches, n_refined = [], 0
    for p in candidates:
        if p in known: y = known[p]
        elif refine: y = labeler(L[p[0]], R[p[1]]); n_refined += 1
        else: y = 1
        if y: matches.append(p)
    return FDJResult(matches, candidates, feats, scaffold, Tp, s['n_labeled'], n_refined, sample_recall, feasible,
                     s['n_uniform'], s['n_pos_uniform'], log)


# ---------------------------------------------------------------- LLM-free join audit

def audit_join(left, right, *, rules: Optional[Dict[str, Callable[[Any], Any]]] = None,
               left_name: str = 'left', right_name: str = 'right') -> Dict[str, Any]:
    """Compare match statistics of an identifier join under several canonicalisation rules.

    Fires the warnings from the DAB failure review: match counts that swing with the rule,
    zero-padded ids / `#` decorations on one side only, many unmatched keys, duplicate keys that
    fan a join out. `left` / `right` are lists of keys or {key: count} dicts (e.g. from GROUP BY).
    The first rule is the baseline the swing is measured against.
    """
    rules = rules or {
        'raw': lambda v: canonical_key(v, strip_hash=False),
        'strip_hash_case': lambda v: canonical_key(v),
        'numeric_id': lambda v: canonical_key(v, numeric=True),
        'ocr_fold_digits': lambda v: canonical_key(v, ocr=True),
    }
    stats, warnings = {}, []

    def counts(values, fn):
        c, nulls = Counter(), 0
        items = values.items() if isinstance(values, dict) else ((v, 1) for v in values)
        for v, n in items:
            k = fn(v)
            if k is None: nulls += n
            else: c[k] += n
        return c, nulls
    for name, fn in rules.items():
        lc, lnull = counts(left, fn); rc, rnull = counts(right, fn)
        common = set(lc) & set(rc)
        pairs = sum(lc[k] * rc[k] for k in common)
        fan = sum(1 for k in common if lc[k] > 1 and rc[k] > 1)
        stats[name] = {'left_keys': len(lc), 'right_keys': len(rc), 'left_null': lnull, 'right_null': rnull,
                       'matched_keys': len(common), 'left_matched_rows': sum(lc[k] for k in common),
                       'right_matched_rows': sum(rc[k] for k in common), 'join_rows': pairs,
                       'left_unmatched_rows': sum(lc[k] for k in lc if k not in common),
                       'right_unmatched_rows': sum(rc[k] for k in rc if k not in common),
                       'many_to_many_keys': fan, 'left_dup_keys': sum(1 for k in lc if lc[k] > 1),
                       'right_dup_keys': sum(1 for k in rc if rc[k] > 1)}
    counts_by_rule = {n: s['matched_keys'] for n, s in stats.items()}
    baseline = next(iter(rules)); best = max(counts_by_rule, key=counts_by_rule.get)
    if counts_by_rule[best] and counts_by_rule[baseline] < 0.9 * counts_by_rule[best]:
        warnings.append(f"match count swings with the key rule: {baseline}={counts_by_rule[baseline]} vs {best}={counts_by_rule[best]}; "
                        f"canonicalise keys ({best}) before joining")
    for side, vals in ((left_name, left), (right_name, right)):
        keys = list(vals.keys()) if isinstance(vals, dict) else list(vals)
        sample = [str(v) for v in keys[:2000] if v is not None]
        if sample and sum(1 for v in sample if v.strip().startswith('#')) > 0.05 * len(sample):
            warnings.append(f'{side}: >5% of keys carry a leading "#"')
        # zero-padded numeric ids: an optional non-digit prefix, then zeros, then the number (tt0000042, Kw00002083)
        if sample and sum(1 for v in sample if re.fullmatch(r'[^0-9]*0+\d+', v.strip())) > 0.2 * len(sample):
            warnings.append(f'{side}: >20% of keys are zero-padded numbers behind a prefix; compare as integers, not digit strings')
    st = stats[best]
    tot_l = st['left_matched_rows'] + st['left_unmatched_rows']; tot_r = st['right_matched_rows'] + st['right_unmatched_rows']
    if tot_l and st['left_unmatched_rows'] / tot_l > 0.2:
        warnings.append(f"{left_name}: {st['left_unmatched_rows']}/{tot_l} rows have no partner even under rule {best}")
    if tot_r and st['right_unmatched_rows'] / tot_r > 0.2:
        warnings.append(f"{right_name}: {st['right_unmatched_rows']}/{tot_r} rows have no partner even under rule {best}")
    if st['many_to_many_keys']:
        warnings.append(f"{st['many_to_many_keys']} keys are duplicated on both sides: the join fans out ({st['join_rows']} rows)")
    return {'rules': stats, 'best_rule': best, 'warnings': warnings}
