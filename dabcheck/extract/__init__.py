"""DocETL-style extraction (Shankar, Chambers, Shah, Parameswaran, Wu; VLDB 2025).

Operators (Sec. 2): map, parallel_map, filter, reduce (batched folding with a scratchpad),
resolve (entity canonicalisation), unnest, split, gather. LLM-centric rewrites (Sec. 3):
gleaning (validator + refinement rounds), projection synthesis (chaining / isolating),
duplicate-key resolution before reduce. Optimizer (Sec. 4): validation agents synthesise
task-specific criteria, candidate plans run on a sample, the best plan is kept.

The DAB-specific entry point is `extract_values`: a code-first extraction pipeline that
reports parse coverage, keeps raw and parsed values side by side, and only sends the rows
the code could not parse to the LLM (with gleaning).
"""
from .numbers import parse_number, parse_amount, find_numbers, words_to_number
from .coverage import CodeExtractor, ExtractSpec, coverage_report
from .ops import map_op, parallel_map, filter_op, reduce_op, resolve, unnest, split, gather
from .gleaning import glean
from .pipeline import extract_values, ExtractionResult
from .optimizer import synthesize_validation, rate_outputs, rewrite_map, optimize_map

__all__ = ['parse_number', 'parse_amount', 'find_numbers', 'words_to_number', 'CodeExtractor', 'ExtractSpec',
           'coverage_report', 'map_op', 'parallel_map', 'filter_op', 'reduce_op', 'resolve', 'unnest', 'split',
           'gather', 'glean', 'extract_values', 'ExtractionResult', 'synthesize_validation', 'rate_outputs',
           'rewrite_map', 'optimize_map']
