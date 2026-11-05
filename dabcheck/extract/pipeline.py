"""Code-first extraction pipeline for a text column (the DAB 'Extraction and representation' fix).

Plan (a DocETL rewrite of the single map "extract X from each row"):
  1. code map: regex patterns + parsers (cheap, exact)                        -> coverage report
  2. LLM map on the rows the code could not parse, with evidence validation    (optional)
  3. gleaning round on the LLM rows                                            (optional)
  4. representation check: value type/unit, truncation signals
Raw text and parsed value are kept side by side so the agent can audit every row.
"""
from __future__ import annotations
import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

from ..llm import BaseLLM
from .coverage import CodeExtractor, ExtractSpec, coverage_report
from .gleaning import glean
from .numbers import parse_number


@dataclass
class ExtractionResult:
    rows: List[Dict[str, Any]]
    coverage: Dict[str, Any]
    warnings: List[str] = field(default_factory=list)
    llm_rows: int = 0

    def values(self) -> List[Any]: return [r['value'] for r in self.rows]

    def summary(self) -> Dict[str, Any]:
        src = {}
        for r in self.rows: src[r.get('source')] = src.get(r.get('source'), 0) + 1
        return {'rows': len(self.rows), 'by_source': src, 'code_coverage': self.coverage['coverage'],
                'final_coverage': sum(1 for r in self.rows if r['value'] is not None) / max(1, len(self.rows)),
                'warnings': self.warnings}


def _evidence_ok(text: str, out: Dict[str, Any]) -> bool:
    """The LLM must quote a verbatim substring that supports the value, and the value must be
    consistent with the number in that evidence (guards against hallucinated numbers)."""
    ev = str(out.get('evidence') or '')
    if out.get('value') in (None, ''): return True      # an honest null is acceptable
    if not ev or ev.strip() not in str(text): return False
    v = out.get('value')
    if isinstance(v, str) and not isinstance(v, bool):
        from .numbers import parse_number
        parsed = parse_number(v)
        if parsed is not None: v = parsed          # '99999' is a number too
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        from .numbers import find_numbers
        nums = [n for n, _, _ in find_numbers(ev)]
        return any(abs(n - float(v)) <= 1e-6 * max(1, abs(float(v))) for n in nums) if nums else False
    return True


def extract_values(texts: Sequence[Any], spec: ExtractSpec, llm: Optional[BaseLLM] = None, *, use_llm: bool = True,
                   gleaning_rounds: int = 1, model: Optional[str] = None, max_llm_rows: Optional[int] = None,
                   context: str = '', workers: int = 1) -> ExtractionResult:
    code = CodeExtractor(spec)
    rows = [code(t) for t in texts]
    cov = coverage_report(texts, rows, spec)
    warnings = list(cov['warnings'])
    llm_rows = 0; refusals: List[int] = []
    if llm is not None and use_llm:
        todo = [i for i, r in enumerate(rows) if r['value'] is None and texts[i] not in (None, '')]
        if max_llm_rows is not None: todo = todo[:max_llm_rows]
        prompt = (f'{context}\nExtract "{spec.name}" ({spec.description or spec.name}'
                  f'{(" in " + spec.unit) if spec.unit else ""}) from the text below. If the text does not state it exactly, return null.\n'
                  'Text: {{ input.text }}')
        schema = {'value': 'number or string or null', 'evidence': 'verbatim substring of the text that states the value'}
        validation = ('Is the value exactly stated by the evidence, is the evidence a verbatim quote, '
                      'and is it the quantity asked for (not a different number in the text)? '
                      'If the text only gives a vague magnitude, the value must be null.')

        def one(i):
            try:
                return glean(llm, {'text': str(texts[i])}, prompt, schema, max_rounds=gleaning_rounds, model=model,
                             validation_prompt=validation)
            except RuntimeError as e:   # a safety refusal on one row yields no value for that row, not a failed column
                if 'model refused' not in str(e): raise
                refusals.append(i); return {'value': None, 'evidence': ''}
        if workers > 1 and len(todo) > 1:   # rows are independent (DocETL runs map in parallel)
            from concurrent.futures import ThreadPoolExecutor
            with ThreadPoolExecutor(max_workers=workers) as pool: outs = list(pool.map(one, todo))
        else:
            outs = [one(i) for i in todo]
        for i, out in zip(todo, outs):
            doc = {'text': str(texts[i])}
            if not isinstance(out, dict): out = {'value': out, 'evidence': ''}
            if isinstance(out.get('value'), bool): out['value'] = None      # true/false is not an extracted value
            if _evidence_ok(doc['text'], out):
                v = out.get('value')
                if spec.parse in ('number', 'amount', 'int') and isinstance(v, str): v = parse_number(v)
                if spec.parse == 'int' and isinstance(v, float): v = int(v)
                rows[i] = {'value': v, 'raw': out.get('evidence'), 'pattern': None, 'source': 'llm' if v is not None else None, 'span': None}
            llm_rows += 1
    if llm is not None and use_llm and refusals:
        warnings.append(f'{spec.name}: the LLM refused {len(refusals)} rows; they have no value')
    final = sum(1 for r in rows if r['value'] is not None) / max(1, len(rows))
    if final < spec.min_coverage:
        warnings.append(f'{spec.name}: final coverage {final:.1%} after code+LLM; the answer may rest on a subset of rows')
    if spec.parse in ('number', 'amount', 'int'):
        vals = [r['value'] for r in rows if isinstance(r['value'], (int, float))]
        if vals and spec.parse != 'text':
            small = sum(1 for v in vals if 0 < v < 1000); 
            if cov['suspected_truncations'] and small > 0.5 * len(vals):
                warnings.append(f'{spec.name}: most parsed values are < 1000 and truncation signals fired; check thousands separators')
    return ExtractionResult(rows, cov, warnings, llm_rows)
