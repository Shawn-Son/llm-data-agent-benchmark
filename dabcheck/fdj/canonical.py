"""Code featurizations for identifier joins.

These are the extraction functions FDJ would generate for the DAB identifier problems
(imdb `tt0000042` -> 42, crmarenapro `#001Wt...`, usaspending OCR folds, cve noisy
keys). They are cheap, deterministic and reusable by `audit_join`.
"""
from __future__ import annotations
import re
from typing import Iterable, List, Optional

OCR_MAP = str.maketrans({'O': '0', 'I': '1', 'S': '5', 'Z': '2', 'G': '6', 'B': '8'})   # applied after upper-casing


def numeric_id(value) -> Optional[int]:
    """Embedded integer id: strip alphabetic prefix, punctuation padding and leading zeros.

    imdb hint: `tt0000042` -> 42, `nm001` -> 1, `InfT~~7` -> 7. Plain ints pass through.
    """
    if value is None: return None
    if isinstance(value, bool): return None
    if isinstance(value, int): return value
    if isinstance(value, float): return int(value) if value == int(value) else None
    digits = re.sub(r'\D', '', str(value))
    return int(digits) if digits else None


def strip_decorations(value) -> Optional[str]:
    """Trim whitespace and a leading '#' (crmarenapro hint); keep case."""
    if value is None: return None
    s = str(value).strip()
    if s.startswith('#'): s = s[1:].strip()
    return s or None


def ocr_fold(value, digits_only: bool = False) -> Optional[str]:
    """Fold OCR look-alikes (0/O, 1/I/l, 5/S, 2/Z, 6/G, 8/B) into digits, upper-case the rest.

    With digits_only=True every non-alphanumeric separator is dropped too (usaspending
    hint: prefixes, case, separators at letter/digit boundaries).
    """
    if value is None: return None
    s = str(value).strip().upper().translate(OCR_MAP)   # upper first: 'ks5' and 'KS5' must fold alike
    if digits_only: s = re.sub(r'[^0-9A-Z]', '', s)
    return s or None


def canonical_key(value, *, ocr: bool = False, numeric: bool = False, strip_hash: bool = True) -> Optional[str]:
    """One-stop canonicaliser used by audit_join; returns a string key or None."""
    if value is None: return None
    s = str(value)
    if strip_hash: s = strip_decorations(s) or ''
    if numeric:
        n = numeric_id(s); return None if n is None else str(n)
    if ocr: s = ocr_fold(s, digits_only=True) or ''
    s = s.strip().lower()
    return s or None


_CVE = re.compile(r'(?:cve)?\W{0,3}(19\d\d|20\d\d)\W{0,3}(\d{4,7})', re.I)


def cve_candidates(value) -> List[str]:
    """Candidate canonical CVE ids (`2023-12345`) readable from a noisy key.

    Covers the plain `CVE-YYYY-NNNN` form with wrapper text and separators. The DAB cve
    keys also use offsets, base encodings and reordering; those families are what the
    FDJ candidate-generation loop is for (an LLM proposes decoders from labelled pairs),
    so this function is only the first, cheapest featurization.
    """
    if value is None: return []
    s = str(value).upper().translate(OCR_MAP)
    return sorted({f'{y}-{int(n)}' for y, n in _CVE.findall(s)})


def canonical_name(value) -> Optional[str]:
    """Entity-name key: lower-case, drop punctuation and common corporate suffixes."""
    if value is None: return None
    s = re.sub(r'[^0-9a-z ]+', ' ', str(value).lower())
    s = re.sub(r'\b(the|inc|incorporated|llc|l l c|ltd|limited|corp|corporation|co|company|plc|lp|llp|gmbh|sa|ag)\b', ' ', s)
    s = re.sub(r'\s+', ' ', s).strip()
    return s or None
