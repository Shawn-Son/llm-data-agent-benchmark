"""Logical scaffolds, cost estimation and threshold setting (paper Sec. 6).

A scaffold is a CNF over predicate scaffolds `phi_f(l, r) <= theta`: a list of clauses,
each clause a list of featurization indices (disjunction), clauses conjoined.
"""
from __future__ import annotations
import itertools, math
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


def recall_and_fpr(flags: Sequence[bool], labels: Sequence[int]) -> Tuple[float, float]:
    """R_S = |Pi(S_p)| / |S_p|; F_S = |Pi(S_n)| / |Pi(S)| (Eq. 2 definitions)."""
    tp = sum(1 for f, y in zip(flags, labels) if f and y); fp = sum(1 for f, y in zip(flags, labels) if f and not y)
    npos = sum(1 for y in labels if y)
    recall = tp / npos if npos else 1.0
    fpr = fp / (tp + fp) if (tp + fp) else 0.0
    return recall, fpr


def _candidates(D, labels, f):
    """Thresholds at which the cost can change: distinct finite distances of positive pairs."""
    vals = sorted({D[f][k] for k, y in enumerate(labels) if y and not math.isinf(D[f][k])})
    return vals or [-INF]


def best_thresholds(scaffold: Scaffold, D, labels, T: float, grid_limit: int = 20000) -> Tuple[Optional[Dict[int, float]], float]:
    """Eq. 2: thresholds minimising the false-positive rate subject to recall >= T on the sample.

    Exhaustive over the product of per-predicate candidate thresholds when it is small
    (the usual case: few predicates, few positives); otherwise coordinate descent from the
    most permissive setting.
    """
    preds = scaffold.predicates()
    if not preds:
        flags = [True] * len(labels); r, fpr = recall_and_fpr(flags, labels)
        return ({}, fpr) if r >= T else (None, INF)
    cands = {f: _candidates(D, labels, f) for f in preds}
    size = 1
    for f in preds: size *= len(cands[f])
    best = (None, INF)

    def consider(th):
        nonlocal best
        r, fpr = recall_and_fpr(scaffold.evaluate(D, th), labels)
        if r >= T and (fpr < best[1] or (fpr == best[1] and best[0] is not None and sum(th.values()) < sum(best[0].values()))):
            best = (dict(th), fpr)

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
                    r, fpr = recall_and_fpr(scaffold.evaluate(D, trial), labels)
                    if r >= T and fpr < best[1]:
                        best = (dict(trial), fpr); th = trial; improved = True
    return best


def cost_estimate(scaffold: Scaffold, D, labels, T: float) -> float:
    """hat C_S(scaffold) = min_theta F_S s.t. R_S >= T (inf when the target is unreachable)."""
    return best_thresholds(scaffold, D, labels, T)[1]


def build_scaffold(D, labels, T: float, gamma: float = 0.01, max_predicates: int = 6, log: Optional[list] = None) -> Scaffold:
    """Alg. 4: greedily add conjuncts while the cost drops by >= gamma, then try adding each
    featurization as a disjunct to each clause."""
    nfeat = len(D)
    scaffold = Scaffold()
    remaining = list(range(nfeat))
    current_cost = cost_estimate(scaffold, D, labels, T)
    while remaining and len(scaffold.predicates()) < max_predicates:
        cmin, fmin = INF, None
        for f in remaining:
            trial = scaffold.copy(); trial.clauses.append([f])
            c = cost_estimate(trial, D, labels, T)
            if c < cmin: cmin, fmin = c, f
        # The first conjunct is admitted on a tie so that a disjunction can still be grown from it
        # (Alg. 4 starts from the trivial scaffold TRUE, whose cost no single predicate may beat
        # when the positives form several families; see test_disjunction_can_reduce_cost).
        if fmin is not None and (cmin < current_cost - gamma or (not scaffold.clauses and cmin <= current_cost and cmin < INF)):
            scaffold.clauses.append([fmin]); remaining.remove(fmin); current_cost = cmin
            if log is not None: log.append({'step': 'conjunct', 'feature': fmin, 'cost': cmin})
        else: break
    for f in range(nfeat):
        for ci in range(len(scaffold.clauses)):
            if f in scaffold.clauses[ci]: continue
            trial = scaffold.copy(); trial.clauses[ci].append(f)
            c = cost_estimate(trial, D, labels, T)
            if c < current_cost - gamma:
                scaffold = trial; current_cost = c
                if log is not None: log.append({'step': 'disjunct', 'feature': f, 'clause': ci, 'cost': c})
    th, _ = best_thresholds(scaffold, D, labels, T)
    scaffold.thresholds = th or {}
    return scaffold


def adjusted_recall_target(T: float, n_pos: int, delta: float) -> float:
    """T' > T such that observed recall >= T' on n_pos sampled positives implies true recall >= T
    with probability >= 1 - delta (one-sided normal bound; the paper's Thm. 6.1 gives the exact
    form in its technical report). Capped so that it stays attainable."""
    if n_pos <= 0: return T
    z = {0.01: 2.326, 0.05: 1.645, 0.1: 1.282, 0.2: 0.842}.get(round(delta, 2))
    if z is None:
        import statistics
        z = statistics.NormalDist().inv_cdf(1 - delta)
    tp = T + z * math.sqrt(max(T * (1 - T), 1e-9) / n_pos)
    return min(tp, 1.0)


def set_thresholds(scaffold: Scaffold, D, labels, T: float, delta: float) -> Tuple[Scaffold, float, bool]:
    """Sec. 6.3 / Alg. 5 line 7: thresholds on a fresh labelled sample at the adjusted target.
    Returns (scaffold with thresholds, T', feasible). feasible=False means no thresholds reach T' on
    the sample (the featurizations are too weak); the most permissive thresholds are returned so the
    caller can still report an honest recall estimate."""
    n_pos = sum(1 for y in labels if y)
    Tp = adjusted_recall_target(T, n_pos, delta)
    th, fpr = best_thresholds(scaffold, D, labels, Tp)
    feasible = th is not None
    if th is None:
        th = {f: max((D[f][k] for k, y in enumerate(labels) if y and not math.isinf(D[f][k])), default=INF)
              for f in scaffold.predicates()}
    out = scaffold.copy(); out.thresholds = th
    return out, Tp, feasible
