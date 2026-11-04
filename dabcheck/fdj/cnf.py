"""Logical scaffolds, cost estimation and threshold setting (paper Sec. 6; reference code
fdj/create_fd/get_join_features.py and select_thresholds.py).

A scaffold is a CNF over predicate scaffolds `phi_f(l, r) <= theta`: a list of clauses, each
clause a list of featurization indices (disjunction), clauses conjoined.

Cost: `cost_mode='fpr'` is the paper's F_S = |Pi(S_n)| / |Pi(S)| (Eq. 2, used in the Fig. 6
example); `cost_mode='neg'` is what the reference implementation minimises, the number of
negatives that pass divided by |S_n| (its gamma is 0.2 of the negatives).
"""
from __future__ import annotations
import functools, itertools, math, random
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

INF = math.inf


@dataclass
class Scaffold:
    clauses: List[List[int]] = field(default_factory=list)   # indices into the featurization list
    thresholds: Dict[int, float] = field(default_factory=dict)  # set by set_thresholds / best_thresholds

    def predicates(self) -> List[int]:
        return sorted({f for c in self.clauses for f in c})

    def evaluate(self, D: Sequence[Sequence[float]], thresholds: Optional[Dict[int, float]] = None) -> List[bool]:
        """Truth value of the CNF for every pair column of D."""
        th = thresholds if thresholds is not None else self.thresholds
        n = len(D[0]) if D else 0
        out = []
        for k in range(n):
            ok = True
            for clause in self.clauses:
                if not any(D[f][k] <= th.get(f, -INF) for f in clause): ok = False; break
            out.append(ok)
        return out

    def describe(self, feats) -> str:
        if not self.clauses: return 'TRUE'
        parts = []
        for clause in self.clauses:
            lits = [f'{feats[f].name} <= {self.thresholds.get(f, float("nan")):.4g}' for f in clause]
            parts.append('(' + ' OR '.join(lits) + ')')
        return ' AND '.join(parts)

    def copy(self) -> 'Scaffold':
        return Scaffold([list(c) for c in self.clauses], dict(self.thresholds))


def recall_and_cost(flags: Sequence[bool], labels: Sequence[int], cost_mode: str = 'fpr') -> Tuple[float, float]:
    """recall R_S = |Pi(S_p)| / |S_p|; cost: 'fpr' -> |Pi(S_n)| / |Pi(S)| (paper Eq. 2),
    'neg' -> |Pi(S_n)| / |S_n| (reference implementation)."""
    tp = sum(1 for f, y in zip(flags, labels) if f and y); fp = sum(1 for f, y in zip(flags, labels) if f and not y)
    npos = sum(1 for y in labels if y); nneg = len(labels) - npos
    recall = tp / npos if npos else 1.0
    if cost_mode == 'neg': cost = fp / nneg if nneg else 0.0
    else: cost = fp / (tp + fp) if (tp + fp) else 0.0
    return recall, cost


def recall_and_fpr(flags, labels):   # backwards-compatible name
    return recall_and_cost(flags, labels, 'fpr')


def _candidates(D, labels, f, max_miss: Optional[int] = None):
    """Thresholds at which the cost can change: distinct finite distances of positive pairs.
    With max_miss given (predicate alone must keep >= n_pos - max_miss positives, as in a
    conjunction), only the max_miss + 1 largest values can be optimal (reference pruning)."""
    vals = sorted({D[f][k] for k, y in enumerate(labels) if y and not math.isinf(D[f][k])})
    if not vals: return [-INF]
    if max_miss is not None: vals = vals[-(max_miss + 1):]
    return vals


def best_thresholds(scaffold: Scaffold, D, labels, T: float, grid_limit: int = 50000, cost_mode: str = 'fpr') -> Tuple[Optional[Dict[int, float]], float]:
    """Eq. 2: thresholds minimising the cost subject to recall >= T on the sample.

    Candidate thresholds per predicate are positive-pair distances; for predicates that form a
    singleton clause only the (max_miss + 1) largest matter. Exhaustive over the product when it
    is small, coordinate descent from the most permissive setting otherwise.
    """
    preds = scaffold.predicates()
    if not preds:
        flags = [True] * len(labels); r, cost = recall_and_cost(flags, labels, cost_mode)
        return ({}, cost) if r >= T else (None, INF)
    n_pos = sum(1 for y in labels if y)
    max_miss = int(math.floor((1 - T) * n_pos + 1e-9))
    singleton = {c[0] for c in scaffold.clauses if len(c) == 1}
    cands = {f: _candidates(D, labels, f, max_miss if f in singleton else None) for f in preds}
    size = 1
    for f in preds: size *= len(cands[f])
    best = (None, INF)

    def consider(th):
        nonlocal best
        r, cost = recall_and_cost(scaffold.evaluate(D, th), labels, cost_mode)
        if r >= T and (cost < best[1] or (cost == best[1] and best[0] is not None and sum(th.values()) < sum(best[0].values()))):
            best = (dict(th), cost)

    if size <= grid_limit:
        for combo in itertools.product(*[cands[f] for f in preds]):
            consider(dict(zip(preds, combo)))
    else:
        th = {f: cands[f][-1] for f in preds}; consider(th)
        improved = True
        while improved:
            improved = False
            for f in preds:
                for v in cands[f]:
                    trial = dict(th); trial[f] = v
                    r, cost = recall_and_cost(scaffold.evaluate(D, trial), labels, cost_mode)
                    if r >= T and cost < best[1]:
                        best = (dict(trial), cost); th = trial; improved = True
    return best


def cost_estimate(scaffold: Scaffold, D, labels, T: float, cost_mode: str = 'fpr') -> float:
    """hat C_S(scaffold) = min_theta cost s.t. R_S >= T (inf when the target is unreachable)."""
    return best_thresholds(scaffold, D, labels, T, cost_mode=cost_mode)[1]


def build_scaffold(D, labels, T: float, gamma: float = 0.1, max_predicates: int = 6, log: Optional[list] = None,
                   cost_mode: str = 'fpr') -> Scaffold:
    """Alg. 4: greedily add conjuncts while the cost drops by >= gamma, then repeatedly try adding
    each remaining featurization as a disjunct to each clause (reference: loop until no addition).

    gamma is a fraction of the cost scale: the reference uses 0.2 of the negatives with cost_mode
    'neg'; with the paper's FPR cost 0.1 is a comparable default.
    """
    nfeat = len(D)
    scaffold = Scaffold()
    remaining = list(range(nfeat))
    current_cost = cost_estimate(scaffold, D, labels, T, cost_mode)
    while remaining and len(scaffold.predicates()) < max_predicates:
        cmin, fmin = INF, None
        for f in remaining:
            trial = scaffold.copy(); trial.clauses.append([f])
            c = cost_estimate(trial, D, labels, T, cost_mode)
            if c < cmin: cmin, fmin = c, f
        # The first conjunct is admitted on a tie so that a disjunction can still be grown from it
        # (Alg. 4 starts from the trivial scaffold TRUE, whose cost no single predicate may beat
        # when the positives form several families; see test_disjunction_can_reduce_cost).
        if fmin is not None and (cmin < current_cost - gamma or (not scaffold.clauses and cmin <= current_cost and cmin < INF)):
            scaffold.clauses.append([fmin]); remaining.remove(fmin); current_cost = cmin
            if log is not None: log.append({'step': 'conjunct', 'feature': fmin, 'cost': cmin})
        else: break
    added = True
    while added and scaffold.clauses:
        added = False
        for f in range(nfeat):
            for ci in range(len(scaffold.clauses)):
                if f in scaffold.clauses[ci]: continue
                trial = scaffold.copy(); trial.clauses[ci].append(f)
                c = cost_estimate(trial, D, labels, T, cost_mode)
                if c < current_cost - gamma:
                    scaffold = trial; current_cost = c; added = True
                    if log is not None: log.append({'step': 'disjunct', 'feature': f, 'clause': ci, 'cost': c})
                    break
            if added: break
    th, _ = best_thresholds(scaffold, D, labels, T, cost_mode=cost_mode)
    scaffold.thresholds = th or {}
    return scaffold


# ---------------------------------------------------------------- adjusted recall target (Sec. 6.3)

def _binom_tail(r: int, k: int, p: float) -> float:
    """P(Binomial(k, p) >= r), summed in log space so large k does not overflow."""
    if r <= 0: return 1.0
    if r > k: return 0.0
    if p <= 0: return 0.0
    if p >= 1: return 1.0
    lp, lq = math.log(p), math.log(1 - p)
    terms = [math.lgamma(k + 1) - math.lgamma(i + 1) - math.lgamma(k - i + 1) + i * lp + (k - i) * lq for i in range(r, k + 1)]
    m = max(terms)
    return math.exp(m) * sum(math.exp(t - m) for t in terms)


def adjusted_target_single(k: int, T: float, delta: float) -> float:
    """Reference get_single_thresh_target: the smallest r/k such that, if the true recall were only
    T, observing >= r of k sampled positives would have probability < delta."""
    if k <= 0: return T
    for r in range(int(math.ceil(T * k)), k + 1):
        if _binom_tail(r, k, T) < delta: return r / k
    return 1.0


def _check_if_val_at_i(dim_vals, no_removed, max_miss_allowed, dim_idx, curr_thresh, u):
    if no_removed > max_miss_allowed: return True
    if dim_idx == len(dim_vals) - 1:
        max_can_remove = min(max_miss_allowed - no_removed, len(dim_vals[dim_idx]) - 1)
        curr_dim_val = dim_vals[dim_idx][max_can_remove]
        if sum(curr_thresh + [curr_dim_val]) <= (len(dim_vals) - 1) * u: return False
        return True
    for i in range(len(dim_vals[dim_idx])):
        if not _check_if_val_at_i(dim_vals, no_removed + i, max_miss_allowed, dim_idx + 1, curr_thresh + [dim_vals[dim_idx][i]], u):
            return False
    return True


def _worstcase_success_prob(k: int, t: float, n: int, d: int, T: float, trials: int, rng: random.Random) -> float:
    """Reference prob_worstcase_success_without_replacement_high_dim: Monte Carlo estimate, on a
    worst-case population of n positives in d dimensions, that thresholds chosen at observed recall
    t on k sampled positives keep true recall >= T."""
    neg_thresh_no_pos = int(n * T) - 1 if n * T == int(n * T) else int(math.floor(n * T))
    neg_thresh_left = n - neg_thresh_no_pos
    D = []
    for j in range(d):
        D.extend([[i if idx == j else 0 for idx in range(d)] for i in range(1, neg_thresh_left + 1)])
    zeros = max(0, n - len(D))
    D = [[0] * d] * zeros + D
    no_threshold = neg_thresh_left
    max_miss_allowed = int(math.ceil(k - k * t))
    count = 0
    for _ in range(trials):
        points = rng.sample(D, k)
        non_zeros = [p for p in points if any(p)]
        dim_vals = [sorted({p[i] for p in non_zeros}, reverse=True) or [0] for i in range(d)]
        if _check_if_val_at_i(dim_vals, 0, max_miss_allowed, 0, [], no_threshold): count += 1
    return count / trials


@functools.lru_cache(maxsize=256)
def adjusted_target_high_dim(k: int, n_max: int, T: float, d: int, delta: float, eps: float = 0.01, trials: int = 1000, seed: int = 0) -> float:
    """Reference get_adjusted_thresh_high_dim (single process, fewer trials, cached in memory):
    the smallest observed-recall threshold in {T + 1/k, T + 2/k, ...} whose worst-case success
    probability minus eps is >= 1 - delta; 0 when none qualifies (callers fall back to 1.0)."""
    rng = random.Random(seed)
    res = 1.0 / k
    thresh = T + res
    while thresh < 1:
        p = _worstcase_success_prob(k, thresh, n_max, d, T, trials, rng) - eps
        if p >= 1 - delta: return thresh
        thresh += res
    return 0.0


def adjusted_recall_target(T: float, n_pos: int, delta: float, d: int = 1, n_sampled: Optional[int] = None,
                           n_total: Optional[int] = None, trials: int = 1000) -> float:
    """T' > T for the threshold-setting sample (Sec. 6.3 / reference select_thresholds.get_thresholds).
    d = 1: exact binomial bound. d > 1: the reference's worst-case Monte Carlo bound, which needs an
    upper estimate of the number of positives in the population (Hoeffding from the sampling counts);
    without sampling counts, or when the bound is unattainable, the binomial bound with delta / d
    (a union bound over the predicates) is used."""
    if n_pos <= 0: return T
    if d <= 1: return adjusted_target_single(n_pos, T, delta)
    if n_sampled and n_total and n_sampled > 0:
        delta_3 = delta * 8 / 10; delta_2 = delta / 10
        margin = math.sqrt(math.log(1 / delta_2) / (2 * n_sampled))
        n_max = max(n_pos, int(n_total * (n_pos / n_sampled + margin)))
        tp = adjusted_target_high_dim(n_pos, n_max, float(T), int(d), float(delta_3), trials=trials)
        if tp > 0: return min(tp, 1.0)
    return adjusted_target_single(n_pos, T, delta / d)


def set_thresholds(scaffold: Scaffold, D, labels, T: float, delta: float, cost_mode: str = 'fpr',
                   n_sampled: Optional[int] = None, n_total: Optional[int] = None, trials: int = 1000) -> Tuple[Scaffold, float, bool]:
    """Sec. 6.3 / Alg. 5 line 7: thresholds on a fresh labelled sample at the adjusted target.
    Returns (scaffold with thresholds, T', feasible). feasible=False means no thresholds reach T' on
    the sample (the featurizations are too weak); the most permissive thresholds are returned so the
    caller can still report an honest recall estimate."""
    n_pos = sum(1 for y in labels if y)
    Tp = adjusted_recall_target(T, n_pos, delta, d=len(scaffold.predicates()) or 1, n_sampled=n_sampled, n_total=n_total, trials=trials)
    th, cost = best_thresholds(scaffold, D, labels, Tp, cost_mode=cost_mode)
    feasible = th is not None
    if th is None:
        th = {f: max((D[f][k] for k, y in enumerate(labels) if y and not math.isinf(D[f][k])), default=INF)
              for f in scaffold.predicates()}
    out = scaffold.copy(); out.thresholds = th
    return out, Tp, feasible
