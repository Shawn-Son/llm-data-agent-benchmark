"""FDJ end-to-end (paper Alg. 5) and the LLM-free join audit."""
from __future__ import annotations
import math, random
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from .featurize import Featurization, Pair, distance_matrix, get_candidate_featurizations
from .cnf import Scaffold, build_scaffold, set_thresholds
from .canonical import canonical_key
from ..llm import BaseLLM

Labeler = Callable[[Any, Any], int]   # L_p(l, r) -> 0/1


def llm_labeler(llm: BaseLLM, predicate: str, model: Optional[str] = None) -> Labeler:
    """The join LLM L_p: substitutes the pair into the natural-language predicate."""
    def label(l, r) -> int:
        user = (f'Join condition: "{predicate}"\n\nLEFT record:\n{str(l)[:4000]}\n\nRIGHT record:\n{str(r)[:4000]}\n\n'
                'Does the join condition hold for this pair? Reply with JSON: {"match": true|false, "reason": "..."}')
        out = llm.json(user, model=model or getattr(llm, 'cheap_model', None), max_tokens=300, tag='fdj.label')
        return int(bool(out.get('match'))) if isinstance(out, dict) else 0
    return label


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
    target_feasible: bool = True   # False: no thresholds reached the adjusted target on S'; most permissive thresholds were used
    log: list = field(default_factory=list)

    def summary(self) -> Dict[str, Any]:
        return {'matches': len(self.matches), 'candidates': len(self.candidates),
                'decomposition': self.scaffold.describe(self.featurizations), 'adjusted_target': self.adjusted_target,
                'labeled_pairs': self.n_labeled, 'llm_refinement_calls': self.n_refined, 'sample_recall': self.sample_recall,
                'target_feasible': self.target_feasible}


def _sample_pairs(nL, nR, k, rng, exclude=frozenset()):
    total = nL * nR
    if total <= k: return [(i, j) for i in range(nL) for j in range(nR) if (i, j) not in exclude]
    out, seen = [], set(exclude)
    while len(out) < k:
        p = (rng.randrange(nL), rng.randrange(nR))
        if p not in seen: seen.add(p); out.append(p)
    return out


def _enriched_sample(nL, nR, k, rng, labeler, L, R, min_pos, candidates_fn=None):
    """Uniform sample, topped up with pairs from a cheap candidate generator until it holds
    min_pos positives (the paper sizes k so that enough positives are present; for very
    sparse joins uniform sampling alone would rarely hit one)."""
    pairs = _sample_pairs(nL, nR, k, rng)
    labels = [labeler(L[i], R[j]) for i, j in pairs]
    if sum(labels) < min_pos and candidates_fn is not None:
        extra = [p for p in candidates_fn() if p not in set(pairs)]
        rng.shuffle(extra)
        for p in extra:
            if sum(labels) >= min_pos: break
            pairs.append(p); labels.append(labeler(L[p[0]], R[p[1]]))
    return pairs, labels


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
             labeler: Optional[Labeler] = None, T: float = 0.9, delta: float = 0.1, k: int = 400, k2: int = 400,
             min_pos: int = 15, featurizations: Optional[Sequence[Featurization]] = None, generate: bool = True,
             max_iter: int = 4, alpha: int = 10, beta: int = 20, gamma: float = 0.01, seed: int = 0,
             candidates_fn: Optional[Callable[[], Sequence[Pair]]] = None, refine: bool = True,
             model: Optional[str] = None) -> FDJResult:
    """Approximate semantic join with recall target T and failure probability delta (Alg. 5).

    labeler: L_p; defaults to the LLM with `predicate`. featurizations: seed features (e.g.
    code canonicalisers); generate=False uses only those (no LLM needed for construction).
    candidates_fn: optional cheap generator of likely-positive pairs used only to make sure the
    labelled samples contain >= min_pos positives.
    """
    rng = random.Random(seed)
    if labeler is None:
        if llm is None: raise ValueError('need an llm or a labeler')
        labeler = llm_labeler(llm, predicate, model)
    log: list = []
    nL, nR = len(L), len(R)
    # 1-2. sample S and label it
    pairs, labels = _enriched_sample(nL, nR, k, rng, labeler, L, R, min_pos, candidates_fn)
    n_labeled = len(pairs)
    # 3. candidate featurizations
    feats = list(featurizations or [])
    if generate:
        if llm is None: raise ValueError('generate=True needs an llm')
        feats = get_candidate_featurizations(llm, L, R, pairs, labels, predicate, seed=feats, max_iter=max_iter,
                                             alpha=alpha, beta=beta, model=model, rng=rng, log=log)
    if not feats: raise ValueError('no featurizations available')
    D = distance_matrix(feats, L, R, pairs)
    # 4. scaffold on S
    scaffold = build_scaffold(D, labels, T, gamma=gamma, log=log)
    # 5-7. fresh sample S', thresholds at the adjusted target
    pairs2, labels2 = _enriched_sample(nL, nR, k2, rng, labeler, L, R, min_pos, candidates_fn)
    n_labeled += len(pairs2)
    D2 = distance_matrix(feats, L, R, pairs2)
    scaffold, Tp, feasible = set_thresholds(scaffold, D2, labels2, T, delta)
    from .cnf import recall_and_fpr
    sample_recall = recall_and_fpr(scaffold.evaluate(D2), labels2)[0]
    # 8-9. candidate result
    candidates = evaluate_pairs(feats, scaffold, L, R)
    # 10. refinement with L_p (precision 1)
    known = {p: y for p, y in zip(pairs + pairs2, labels + labels2)}
    matches, n_refined = [], 0
    for p in candidates:
        if p in known: y = known[p]
        elif refine: y = labeler(L[p[0]], R[p[1]]); n_refined += 1
        else: y = 1
        if y: matches.append(p)
    return FDJResult(matches, candidates, feats, scaffold, Tp, n_labeled, n_refined, sample_recall, feasible, log)


# ---------------------------------------------------------------- LLM-free join audit

def audit_join(left: Sequence[Any], right: Sequence[Any], *, rules: Optional[Dict[str, Callable[[Any], Any]]] = None,
               left_name: str = 'left', right_name: str = 'right') -> Dict[str, Any]:
    """Compare match statistics of an identifier join under several canonicalisation rules.

    Fires the warnings from the DAB failure review: match counts that swing with the rule,
    leading zeros / decorations on one side only, many unmatched keys, duplicate keys that
    fan a join out. Returns a dict with per-rule statistics and a list of warnings.
    """
    rules = rules or {
        'raw': lambda v: canonical_key(v, strip_hash=False),
        'strip_hash_case': lambda v: canonical_key(v),
        'numeric_id': lambda v: canonical_key(v, numeric=True),
        'ocr_fold_digits': lambda v: canonical_key(v, ocr=True),
    }
    stats, warnings = {}, []

    def counts(values, fn):
        """values: a list of keys, or a dict {key: count} (e.g. from GROUP BY) for large tables."""
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
    counts = {n: s['matched_keys'] for n, s in stats.items()}
    best = max(counts, key=counts.get)
    if counts[best] and counts['raw'] < 0.9 * counts[best]:
        warnings.append(f"match count swings with the key rule: raw={counts['raw']} vs {best}={counts[best]}; "
                        f"canonicalise keys ({best}) before joining")
    for side, vals in ((left_name, left), (right_name, right)):
        keys = list(vals.keys()) if isinstance(vals, dict) else vals
        sample = [str(v) for v in keys[:2000] if v is not None]
        if sample and sum(1 for v in sample if v.strip().startswith('#')) > 0.05 * len(sample):
            warnings.append(f'{side}: >5% of keys carry a leading "#"')
        # zero-padded numeric ids: an optional non-digit prefix, then zeros, then the number (tt0000042, Kw00002083)
        if sample and sum(1 for v in sample if re.fullmatch(r'[^0-9]*0+\d+', v.strip())) > 0.2 * len(sample):
            warnings.append(f'{side}: >20% of keys are zero-padded numbers behind a prefix; compare as integers, not digit strings')
    s = stats[best]
    tot_l = s['left_matched_rows'] + s['left_unmatched_rows']; tot_r = s['right_matched_rows'] + s['right_unmatched_rows']
    if tot_l and s['left_unmatched_rows'] / tot_l > 0.2:
        warnings.append(f"{left_name}: {s['left_unmatched_rows']}/{tot_l} rows have no partner even under rule {best}")
    if tot_r and s['right_unmatched_rows'] / tot_r > 0.2:
        warnings.append(f"{right_name}: {s['right_unmatched_rows']}/{tot_r} rows have no partner even under rule {best}")
    if s['many_to_many_keys']:
        warnings.append(f"{s['many_to_many_keys']} keys are duplicated on both sides: the join fans out ({s['join_rows']} rows)")
    return {'rules': stats, 'best_rule': best, 'warnings': warnings}


import re  # noqa: E402  (used by audit_join)
