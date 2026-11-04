"""Code-first extraction with a parse-coverage report (the DAB warning: low parse coverage,
truncated numbers, wrong representation)."""
from __future__ import annotations
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence

from .numbers import parse_number, parse_amount


@dataclass
class ExtractSpec:
    """What to extract from a text column.

    patterns: regexes with a named group `value` (tried in order). parse: how to turn the
    captured text into a value ('number', 'amount', 'text', 'int', or a callable).
    requires_all_rows: coverage below `min_coverage` raises a warning.
    """
    name: str
    patterns: Sequence[str] = ()
    parse: Any = 'text'
    description: str = ''
    min_coverage: float = 0.95
    unit: str = ''

    def parser(self) -> Callable[[str], Any]:
        if callable(self.parse): return self.parse
        return {'number': parse_number, 'amount': parse_amount, 'int': lambda s: (lambda v: int(v) if v is not None else None)(parse_number(s)),
                'text': lambda s: s.strip() if s is not None else None}[self.parse]


class CodeExtractor:
    """Apply the spec's patterns; returns {'value', 'raw', 'pattern', 'source': 'code'|None}."""

    def __init__(self, spec: ExtractSpec):
        self.spec = spec; self.regexes = [re.compile(p, re.I | re.S) for p in spec.patterns]; self.parse = spec.parser()

    def __call__(self, text: Any) -> Dict[str, Any]:
        s = '' if text is None else str(text)
        for idx, rx in enumerate(self.regexes):
            for m in rx.finditer(s):
                raw = m.group('value') if 'value' in m.groupdict() else m.group(0)
                try: v = self.parse(raw)
                except Exception: v = None
                if v is not None and v != '':
                    return {'value': v, 'raw': raw, 'pattern': idx, 'source': 'code', 'span': m.span()}
        if not self.regexes:   # no pattern: try to parse the whole cell
            try: v = self.parse(s)
            except Exception: v = None
            if v is not None and v != '': return {'value': v, 'raw': s, 'pattern': None, 'source': 'code', 'span': (0, len(s))}
        return {'value': None, 'raw': None, 'pattern': None, 'source': None, 'span': None}


def coverage_report(texts: Sequence[Any], results: Sequence[Dict[str, Any]], spec: Optional[ExtractSpec] = None,
                    sample: int = 5) -> Dict[str, Any]:
    """Coverage, null rate, per-pattern counts, suspicious truncations, and unparsed samples."""
    n = len(results)
    parsed = [r for r in results if r.get('value') is not None]
    by_pattern: Dict[Any, int] = {}
    for r in parsed: by_pattern[r.get('pattern')] = by_pattern.get(r.get('pattern'), 0) + 1
    unparsed = [str(t)[:160] for t, r in zip(texts, results) if r.get('value') is None and t not in (None, '')]
    empty = sum(1 for t in texts if t in (None, ''))
    # truncation check: the raw capture is immediately preceded by a digit/comma (e.g. '30,522 forks' captured as '522')
    truncated = 0
    for t, r in zip(texts, results):
        sp = r.get('span')
        if sp and r.get('raw') and isinstance(t, str):
            start = sp[0] + str(t)[sp[0]:sp[1]].find(str(r['raw']))
            if start > 0 and re.match(r'[\d,]', str(t)[start - 1]): truncated += 1
    cov = len(parsed) / n if n else 1.0
    warnings = []
    if spec is not None and cov < spec.min_coverage:
        warnings.append(f'{spec.name}: parse coverage {cov:.1%} < {spec.min_coverage:.0%} ({n - len(parsed)} of {n} rows unparsed)')
    if truncated:
        warnings.append(f'{truncated} captures are preceded by digits or commas: the pattern probably truncates numbers with thousands separators')
    if empty and n and empty / n > 0.05:
        warnings.append(f'{empty} of {n} cells are empty')
    return {'rows': n, 'parsed': len(parsed), 'coverage': cov, 'empty': empty, 'by_pattern': by_pattern,
            'suspected_truncations': truncated, 'unparsed_samples': unparsed[:sample], 'warnings': warnings}
