"""Text-to-SQL verification without ground truth (Alrashed, Sukoon, Karger, Noy; VLDB 2026).

Verifiers V(q, s, d) -> accept/reject:
  - round_trip_verify   : SQL -> natural language (isolated from q) -> Likert critique vs q (Sec. 3.2)
  - synthetic_execution : LLM-built test databases, execute s, compare with the LLM's expected answer (Sec. 3.3)
  - sql_critique        : direct critique baseline (TrustSQL ERROR_P; Sec. 3.1)
  - cohort_check        : data-agent extension: structured intent cards (population, filters,
                          time field, window, denominator, ranking) from q and from s, compared
                          field by field; targets the "wrong population / wrong time window" errors
Combine with AND (conservative) or OR (permissive); `selective` turns a generator into one
that abstains when the verifier rejects (Sec. 7).
"""
from .schema import Schema, Table, Column, schema_from_sqlite, schema_from_duckdb, schema_from_ddl, render_schema
from .synthexec import synthesize_cases, execute_sql, results_match, synthetic_execution_verify, normalize_result
from .roundtrip import back_translate, critique_questions, round_trip_verify
from .critique import sql_critique
from .cohort import intent_card_from_question, intent_card_from_sql, compare_cards, cohort_check
from .verify import verify_sql, selective

__all__ = ['Schema', 'Table', 'Column', 'schema_from_sqlite', 'schema_from_duckdb', 'schema_from_ddl', 'render_schema',
           'synthesize_cases', 'execute_sql', 'results_match', 'synthetic_execution_verify', 'normalize_result',
           'back_translate', 'critique_questions', 'round_trip_verify', 'sql_critique', 'intent_card_from_question',
           'intent_card_from_sql', 'compare_cards', 'cohort_check', 'verify_sql', 'selective']
