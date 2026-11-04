# Offline experiments on DataAgentBench data

Each script needs the pinned DataAgentBench checkout with its data downloaded (`DAB_ROOT`, default
`~/DataAgentBench`) and no API key. Results are written to `results/<name>.json` and `.md`.

| Script | Question(s) | Module | Minutes |
|---|---|---|---:|
| `exp_imdb_join_audit.py` | imdb q6, q10 | `fdj.audit_join` | 1 (first run loads 4.5M rows into a temp sqlite file) |
| `exp_deps_extraction.py` | DEPS_DEV_V1 q1, q2 | `extract.extract_values` | < 1 |
| `exp_usaspending_amounts.py` | usaspending q1 | `extract.parse_amount`, `fdj.audit_join` | < 1 |
| `exp_cve_fdj.py` | cve q3, q8, q10 | `fdj.fdj_join` with the corruption code as oracle | 3-4 |
| `exp_crm_sql_verify.py` | crmarenapro q12 | `sqlverify` synthetic execution and intent cards | < 1 |

With an API key, the same modules run their LLM-backed parts: `python -m dabcheck verify-sql ...`,
`python -m dabcheck fdj left.csv right.csv --predicate "..."`, and `extract_values(..., llm=get_llm())`.
