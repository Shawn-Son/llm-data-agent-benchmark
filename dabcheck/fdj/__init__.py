"""Featurized-Decomposition Join (FDJ), after Zeighami, Shankar and Parameswaran, VLDB 2026.

Pipeline (paper Alg. 5):
  1. sample pairs from L x R and label them with the join LLM (or an oracle);
  2. generate candidate featurizations (Alg. 1-3: LLM proposes feature extractors and
     a distance function; cost-to-cover picks the examples for the next round);
  3. build a logical scaffold in CNF greedily (Alg. 4) minimising the false-positive
     rate at the recall target;
  4. set predicate thresholds on a fresh sample with an adjusted recall target (Sec. 6.3);
  5. evaluate the decomposition on every pair, then refine the candidates with the LLM
     (precision 1 by construction, recall >= T with probability >= 1 - delta).

`audit_join` is the cheap, LLM-free check a data agent can run on any identifier join.
"""
from .distances import DISTANCES, register_distance
from .canonical import numeric_id, canonical_key, ocr_fold, strip_decorations, cve_candidates, canonical_name
from .featurize import Featurization, CodeExtractor, LLMExtractor, cost_to_cover, generate_featurizations, get_candidate_featurizations
from .cnf import Scaffold, build_scaffold, best_thresholds, cost_estimate, set_thresholds, adjusted_recall_target
from .join import fdj_join, audit_join, FDJResult

__all__ = ['DISTANCES', 'register_distance', 'numeric_id', 'canonical_key', 'ocr_fold', 'strip_decorations', 'cve_candidates', 'canonical_name',
           'Featurization', 'CodeExtractor', 'LLMExtractor', 'cost_to_cover', 'generate_featurizations',
           'get_candidate_featurizations', 'Scaffold', 'build_scaffold', 'best_thresholds', 'cost_estimate',
           'set_thresholds', 'adjusted_recall_target', 'fdj_join', 'audit_join', 'FDJResult']
