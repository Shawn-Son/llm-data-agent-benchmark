"""Cohort / temporal intent check (data-agent extension of round-trip critique).

Instead of a single Likert score, both the question and the SQL are reduced to a structured
intent card, and the cards are compared field by field. Deterministic checks catch time-window
and date-field drift; the LLM judges population, filter and denominator equivalence.
"""
from __future__ import annotations
import datetime as dt
import json, re
from typing import Any, Dict, List, Optional

from ..llm import BaseLLM
from .schema import Schema, render_schema

CARD = {
    'population': 'which entities are counted/aggregated, as a sentence (tables, joins)',
    'filters': ['each filter condition in words'],
    'event_date_field': 'the date/time column (or concept) the time window applies to, or null',
    'time_window': {'start': 'ISO date or null', 'end': 'ISO date or null', 'end_inclusive': 'true|false'},
    'as_of_logic': 'any "latest record on or before X" / status-as-of rule, or null',
    'aggregate': 'the aggregate computed (count distinct X, sum of Y, average of Z, ...)',
    'denominator': 'for ratios/averages: what is in the denominator, or null',
    'group_by': ['grouping keys'],
    'ranking': {'metric': 'what is ranked, or null', 'direction': 'asc|desc|null', 'limit': 'integer or null'},
    'output': ['output columns / the reported value'],
}
SYSTEM = 'You extract the precise analytical intent of questions and queries as structured cards. Never invent details that are absent.'


def _card(llm: BaseLLM, text: str, kind: str, schema: Schema, model: Optional[str]) -> Dict[str, Any]:
    what = 'question' if kind == 'question' else 'SQL query'
    user = (f'Schema:\n{render_schema(schema)}\n\n{what.capitalize()}:\n{text}\n\n'
            f'Fill this intent card for the {what} only (use null where the {what} says nothing):\n' + json.dumps(CARD) +
            '\nReply with the JSON card.')
    out = llm.json(user, SYSTEM, model=model, max_tokens=1200, tag=f'sqlverify.cohort.card.{kind}')
    return out if isinstance(out, dict) else {}


def intent_card_from_question(llm, question, schema, model=None): return _card(llm, question, 'question', schema, model)


def intent_card_from_sql(llm, sql, schema, model=None): return _card(llm, sql, 'sql', schema, model)


def _date(s) -> Optional[dt.date]:
    if not s or not isinstance(s, str): return None
    m = re.search(r'(\d{4})-(\d{2})-(\d{2})', s)
    if m: return dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    m = re.fullmatch(r'\s*(\d{4})-(\d{2})\s*', s)
    if m: return dt.date(int(m.group(1)), int(m.group(2)), 1)
    m = re.fullmatch(r'\s*(\d{4})\s*', s)
    if m: return dt.date(int(m.group(1)), 1, 1)
    return None


_STOP = {'the', 'of', 'on', 'a', 'an', 'date', 'datetime', 'time', 'field', 'column', 'at', 'in', 'by', 'its', 'their', 'when', 'was', 'is'}


def _field_tokens(name: str) -> set:
    s = re.sub(r'([a-z])([A-Z])', r'\1 \2', name)            # CamelCase -> words
    toks = {t for t in re.split(r'[^a-zA-Z]+', s.lower()) if t and t not in _STOP}
    return {t[:-1] if t.endswith('s') else t for t in toks}   # crude plural fold


def _same_field(a: str, b: str) -> bool:
    """Do two date-field descriptions name the same concept? 'contract company-signed (closing) date'
    vs 'Contract.CompanySignedDate' -> yes; vs 'Opportunity.CreatedDate' -> no."""
    ta, tb = _field_tokens(a), _field_tokens(b)
    if not ta or not tb: return True
    inter = len(ta & tb)
    return inter / min(len(ta), len(tb)) >= 0.5


def compare_cards(llm: Optional[BaseLLM], q_card: Dict[str, Any], s_card: Dict[str, Any], model: Optional[str] = None) -> Dict[str, Any]:
    warnings: List[str] = []
    qw, sw = q_card.get('time_window') or {}, s_card.get('time_window') or {}
    qs, qe, ss, se = _date(qw.get('start')), _date(qw.get('end')), _date(sw.get('start')), _date(sw.get('end'))
    if (qs or qe) and not (ss or se): warnings.append('time window: the question bounds a period but the SQL applies no date window')
    if qs and ss and qs != ss: warnings.append(f'time window start differs: question {qs} vs SQL {ss}')
    if qe and se:
        qi = str(qw.get('end_inclusive', 'true')).lower() != 'false'; si = str(sw.get('end_inclusive', 'true')).lower() != 'false'
        q_last = qe if qi else qe - dt.timedelta(days=1); s_last = se if si else se - dt.timedelta(days=1)
        if q_last != s_last: warnings.append(f'time window end differs: question through {q_last} vs SQL through {s_last}')
    qf, sf = q_card.get('event_date_field'), s_card.get('event_date_field')
    if qf and sf and not _same_field(str(qf), str(sf)):
        warnings.append(f'date field: the question anchors the period on "{qf}" but the SQL filters on "{sf}"')
    if q_card.get('as_of_logic') and not s_card.get('as_of_logic'):
        warnings.append(f'as-of rule missing: the question requires "{q_card["as_of_logic"]}" but the SQL uses static values')
    qr, sr = q_card.get('ranking') or {}, s_card.get('ranking') or {}
    if qr.get('limit') not in (None, '', 'null') and sr.get('limit') not in (None, '', 'null') and str(qr['limit']) != str(sr['limit']):
        warnings.append(f"ranking limit differs: question top {qr['limit']} vs SQL top {sr['limit']}")
    judged = {}
    if llm is not None:
        user = ('Compare these two intent cards field by field. Card Q comes from the question, card S from the SQL.\n'
                'Q: ' + json.dumps(q_card, ensure_ascii=False) + '\nS: ' + json.dumps(s_card, ensure_ascii=False) +
                '\n\nFor each of population, filters, aggregate, denominator, group_by, ranking metric and output: say whether S '
                'satisfies Q ("same"), is narrower, wider, or different, with one sentence of evidence. '
                'Reply with JSON: {"fields": {"<field>": {"verdict": "same|narrower|wider|different|unknown", "evidence": "..."}}}')
        out = llm.json(user, SYSTEM, model=model, max_tokens=1200, tag='sqlverify.cohort.compare')
        judged = out.get('fields', {}) if isinstance(out, dict) else {}
        for fld, v in judged.items():
            if isinstance(v, dict) and v.get('verdict') in ('narrower', 'wider', 'different'):
                warnings.append(f'{fld}: SQL is {v["verdict"]} than the question ({v.get("evidence", "")})')
    return {'warnings': warnings, 'judged': judged}


def cohort_check(llm: BaseLLM, question: str, sql: str, schema: Schema, model: Optional[str] = None) -> Dict[str, Any]:
    qc = intent_card_from_question(llm, question, schema, model)
    sc = intent_card_from_sql(llm, sql, schema, model)
    cmp = compare_cards(llm, qc, sc, model)
    return {'method': 'cohort_check', 'accept': not cmp['warnings'], 'warnings': cmp['warnings'], 'question_card': qc,
            'sql_card': sc, 'judged': cmp['judged'],
            'reason': 'intent cards agree' if not cmp['warnings'] else '; '.join(cmp['warnings'][:3])}
