"""Predefined feature distance functions (paper Sec. 3.1: lexical, arithmetic, set, embedding).

Every distance maps two extracted feature values to a float in [0, inf]; a missing value
(None / NaN / empty) gives inf so the predicate `d <= theta` is false, which is how a
featurized decomposition stays robust to extraction failures.
"""
from __future__ import annotations
import datetime as _dt
import math, re
from typing import Any, Callable, Dict

INF = math.inf


def _missing(v) -> bool:
    if v is None: return True
    if isinstance(v, float) and math.isnan(v): return True
    if isinstance(v, (str, list, tuple, set, dict)) and len(v) == 0: return True
    return False


def _num(v):
    if isinstance(v, bool): return float(v)
    if isinstance(v, (int, float)): return float(v)
    if isinstance(v, str):
        s = v.strip().replace(',', '')
        try: return float(s)
        except ValueError:
            m = re.search(r'-?\d+(?:\.\d+)?', s)
            return float(m.group()) if m else None
    return None


def _tokens(v):
    if isinstance(v, (list, tuple, set)): return {str(x).strip().lower() for x in v if not _missing(x)}
    return {t for t in re.split(r'[^0-9a-zA-Z]+', str(v).lower()) if t}


def _date(v):
    if isinstance(v, _dt.datetime): return v
    if isinstance(v, _dt.date): return _dt.datetime(v.year, v.month, v.day)
    if isinstance(v, (int, float)): return _dt.datetime.fromtimestamp(float(v))
    s = str(v).strip()
    for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%dT%H:%M:%S', '%Y-%m-%d', '%m/%d/%Y', '%d %b %Y', '%B %d, %Y', '%Y/%m/%d', '%Y'):
        try: return _dt.datetime.strptime(s[:len(fmt) + 6] if '%' in fmt else s, fmt)
        except ValueError: continue
    try:
        from dateutil import parser as _p
        return _p.parse(s, fuzzy=True)
    except Exception: return None


def levenshtein(a: str, b: str) -> int:
    if a == b: return 0
    if not a: return len(b)
    if not b: return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def d_exact(a, b):
    if _missing(a) or _missing(b): return INF
    return 0.0 if str(a).strip().lower() == str(b).strip().lower() else 1.0


def d_numeric_abs(a, b):
    x, y = _num(a), _num(b)
    return INF if x is None or y is None else abs(x - y)


def d_numeric_rel(a, b):
    x, y = _num(a), _num(b)
    if x is None or y is None: return INF
    den = max(abs(x), abs(y), 1e-12)
    return abs(x - y) / den


def d_date_days(a, b):
    x, y = (_date(a) if not _missing(a) else None), (_date(b) if not _missing(b) else None)
    return INF if x is None or y is None else abs((x - y).total_seconds()) / 86400.0


def d_token_jaccard(a, b):
    if _missing(a) or _missing(b): return INF
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb: return INF
    return 1.0 - len(ta & tb) / len(ta | tb)


def d_set_overlap(a, b):
    """1 - |A n B| / min(|A|, |B|): small when one side is contained in the other."""
    if _missing(a) or _missing(b): return INF
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb: return INF
    return 1.0 - len(ta & tb) / min(len(ta), len(tb))


def d_char_edit(a, b):
    """Normalised Levenshtein distance on lower-cased strings."""
    if _missing(a) or _missing(b): return INF
    x, y = str(a).strip().lower(), str(b).strip().lower()
    return levenshtein(x, y) / max(len(x), len(y), 1)


def d_digit_edit(a, b):
    """Levenshtein distance between the digit-only projections (for noisy identifiers)."""
    if _missing(a) or _missing(b): return INF
    x, y = re.sub(r'\D', '', str(a)), re.sub(r'\D', '', str(b))
    if not x or not y: return INF
    return float(levenshtein(x, y))


def d_prefix(a, b):
    """0 when one string is a prefix of the other, else 1."""
    if _missing(a) or _missing(b): return INF
    x, y = str(a).strip().lower(), str(b).strip().lower()
    return 0.0 if x.startswith(y) or y.startswith(x) else 1.0


DISTANCES: Dict[str, Callable[[Any, Any], float]] = {
    'exact': d_exact, 'numeric_abs': d_numeric_abs, 'numeric_rel': d_numeric_rel, 'date_days': d_date_days,
    'token_jaccard': d_token_jaccard, 'set_overlap': d_set_overlap, 'char_edit': d_char_edit,
    'digit_edit': d_digit_edit, 'prefix': d_prefix,
}

DESCRIPTIONS = {
    'exact': 'case-insensitive string equality (0 or 1)',
    'numeric_abs': 'absolute difference of two numbers',
    'numeric_rel': 'relative difference |x-y| / max(|x|,|y|)',
    'date_days': 'difference between two dates in days (time optional)',
    'token_jaccard': '1 - Jaccard overlap of word tokens',
    'set_overlap': '1 - |A n B| / min(|A|,|B|) over token sets or lists',
    'char_edit': 'normalised edit distance between strings',
    'digit_edit': 'edit distance between the digit-only parts of two identifiers',
    'prefix': '0 if one string is a prefix of the other, else 1',
}


def register_distance(name: str, fn: Callable[[Any, Any], float], description: str = ''):
    """Add a distance (e.g. an embedding cosine distance) so the LLM may choose it."""
    DISTANCES[name] = fn; DESCRIPTIONS[name] = description or name
