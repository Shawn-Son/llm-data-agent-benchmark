"""Code extractors for numbers written in prose (the usaspending / DEPS_DEV_V1 formats).

Handles: plain and comma-separated integers, decimals, $ prefix / USD suffix, scaled
abbreviations (K / M / B, thousand / million / billion), full English word form, and
sum-of-parts expressions ("$1,050,000 + $450,000"). Every one of these encodes the exact
amount (usaspending hint); vague magnitude prose ("five-figure") is reported as unparsed.
"""
from __future__ import annotations
import re
from typing import List, Optional, Tuple

_UNITS = {'zero': 0, 'one': 1, 'two': 2, 'three': 3, 'four': 4, 'five': 5, 'six': 6, 'seven': 7, 'eight': 8, 'nine': 9,
          'ten': 10, 'eleven': 11, 'twelve': 12, 'thirteen': 13, 'fourteen': 14, 'fifteen': 15, 'sixteen': 16,
          'seventeen': 17, 'eighteen': 18, 'nineteen': 19, 'twenty': 20, 'thirty': 30, 'forty': 40, 'fifty': 50,
          'sixty': 60, 'seventy': 70, 'eighty': 80, 'ninety': 90}
_SCALES = {'hundred': 100, 'thousand': 10 ** 3, 'million': 10 ** 6, 'billion': 10 ** 9, 'trillion': 10 ** 12}
_ABBREV = {'k': 10 ** 3, 'm': 10 ** 6, 'mm': 10 ** 6, 'b': 10 ** 9, 'bn': 10 ** 9, 't': 10 ** 12}
_WORD = re.compile(r'\b(?:' + '|'.join(list(_UNITS) + list(_SCALES) + ['and', 'a']) + r')\b(?:[\s-]+(?:' +
                   '|'.join(list(_UNITS) + list(_SCALES) + ['and', 'a']) + r')\b)*', re.I)


def words_to_number(text: str) -> Optional[float]:
    """'one million five hundred thousand' -> 1500000; 'a hundred' -> 100; None when not a number phrase."""
    words = [w for w in re.split(r'[\s-]+', text.strip().lower()) if w and w != 'and']
    if not words or all(w == 'a' for w in words): return None
    total, current, seen = 0.0, 0.0, False
    for w in words:
        if w == 'a': current = max(current, 1); continue
        if w in _UNITS: current += _UNITS[w]; seen = True
        elif w == 'hundred': current = (current or 1) * 100; seen = True
        elif w in _SCALES:
            total += (current or 1) * _SCALES[w]; current = 0; seen = True
        else: return None
    return (total + current) if seen else None


_NUM = r'(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?'
# A single-letter scale (1.5M, 750K, 2B) must be attached to the number; a word scale may follow a space.
# "100 m" or "5 t" are units, not scales.
_MONEY = re.compile(r'(?P<cur>\$|usd\s*|us\$)?\s*(?P<num>' + _NUM + r')(?:(?P<scale>k|m|mm|b|bn|t)|\s*(?P<wscale>thousand|million|billion|trillion))?\b\s*(?P<sfx>usd|dollars?)?', re.I)


def parse_number(token: str) -> Optional[float]:
    """One numeric token with optional currency marks and scale: '$1.5M' -> 1500000, '30,522' -> 30522."""
    if token is None: return None
    s = str(token).strip().rstrip(',.;:')   # a capture such as '7,201,' from "a forks count of 7,201, making"
    if not s: return None
    m = _MONEY.fullmatch(s)
    if m:
        v = float(m.group('num').replace(',', ''))
        sc = (m.group('scale') or m.group('wscale') or '').lower()
        if sc: v *= _ABBREV.get(sc, _SCALES.get(sc, 1))
        return v
    m = _MONEY.match(s)
    if m and m.group('num') and re.fullmatch(r'\s*[A-Za-z]{1,3}\.?', s[m.end():]):   # '100 m', '5 t': a unit, not a scale
        return parse_number(m.group(0))
    w = words_to_number(s.replace('dollars', '').replace('usd', ''))
    return w


def find_numbers(text: str) -> List[Tuple[float, str, Tuple[int, int]]]:
    """All numeric mentions in a text: (value, matched text, span). Digits and word forms."""
    out = []
    if not text: return out
    taken = []
    for m in _MONEY.finditer(text):
        if not m.group('num'): continue
        v = parse_number(m.group(0))
        if v is not None: out.append((v, m.group(0).strip(), m.span())); taken.append(m.span())
    for m in _WORD.finditer(text):
        if any(a < m.end() and m.start() < b for a, b in taken): continue   # "5 million": the word is part of the number
        v = words_to_number(m.group(0))
        if v is not None and v > 0: out.append((v, m.group(0).strip(), m.span()))
    out.sort(key=lambda t: t[2][0])
    return out


_SUM_SPLIT = re.compile(r'\s*(?:\+|plus|and then|,\s*plus)\s*', re.I)


def parse_amount(text: str) -> Optional[float]:
    """Exact dollar amount from any of the usaspending text formats, or None when the text is vague
    magnitude prose ('five-figure', 'low-to-mid millions') or holds no number at all."""
    if text is None: return None
    s = str(text).strip()
    if not s: return None
    if re.search(r'\b(figure|figures|low|mid|high|roughly|around|about|approximately|range|between|under|over|more than|less than)\b', s, re.I) \
            and not re.search(r'\d', s):
        return None
    if not re.search(r'\d', s):
        # Without digits, only a cell that is entirely a number phrase is an exact amount ("one million five hundred
        # thousand dollars"). A stray number word inside prose ("a million-dollar tier", "FOUR POINTS TECHNOLOGY")
        # is not: on usaspending this rule produced 159 false values out of 681 before it was added.
        bare = re.sub(r'\b(?:dollars?|usd|us)\b|\$|[.,;:]', ' ', s, flags=re.I)
        bare = re.sub(r'(?<!\w)\+(?!\w)', ' + ', bare)
        if not all(_WORD.fullmatch(part.strip()) for part in re.split(r'\s*(?:\+|\bplus\b)\s*', bare, flags=re.I) if part.strip()):
            return None
    parts = [p for p in _SUM_SPLIT.split(s) if p.strip()]
    vals = []
    for p in parts:
        v = parse_number(p)
        if v is None:
            found = find_numbers(p)
            if len(found) == 1: v = found[0][0]
            elif len(found) > 1 and not re.search(r'\d', p):   # word form with several scale phrases
                v = words_to_number(re.sub(r'[^a-z\s-]', ' ', p.lower()))
        if v is None: return None
        vals.append(v)
    return sum(vals) if vals else None
