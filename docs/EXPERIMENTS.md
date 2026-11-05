# Method conditions: one paper method per failure category (Haiku only)

Three new conditions of the 104-question sweep, each run once (`--trial 1`; trial 2 was cancelled for time) with
`claude-haiku-5-5` as the agent and as every LLM inside the method. Prompts, data, sandbox and the
original validators are the same as in the Haiku baseline (`haiku-claude-104x3`, trials 1-2).

| Condition | Failure category | Method | When it acts | Agent sees |
|---|---|---|---|---|
| `--method fdj` | Identifier joins and identity | FDJ (Zeighami et al., VLDB 2026) | once per dataset, before the sweep | `./dabcheck_prep/` with join pairs / entity clusters + README, and a prompt note |
| `--method docetl` | Extraction and representation | DocETL code-first map + gleaning (Shankar et al., VLDB 2025) | once per dataset, before the sweep | `./dabcheck_prep/` with extracted values + README, and a prompt note |
| `--method sqlverify` | Cohort / temporal | Text-to-SQL verification: RT + SE + cohort cards, AND (Alrashed et al., VLDB 2026) | after round 1, harness-side | nothing in round 1; on a rejection, a second session with the warnings |

Design rules
- Preprocessing is **dataset-level** (`dabcheck/specs.py`): which columns hold noisy keys or prose numbers,
  as the database descriptions and hints already state. Nothing is written for a particular question.
- Datasets without a usable preprocessing output keep the baseline prompt byte for byte.
- The fdj / docetl conditions give the method's outputs only (no `audit_join`, no code tools).
- sqlverify verifies the last 2 answer-level SQL statements the agent ran that belong to one SQL database
  (sqlite, duckdb, or a postgres dump); MongoDB work cannot be verified. A verifier error counts as an accept.
  A Haiku call first classifies each of the last 8 single-database statements as answer-level or fetch/inspect.
  The official answer of a question is the round-2 answer when round 2 ran; round 1 is kept
  (`answer_round1.txt`, `grading_round1.json`, `round1_passed` in `result.json`).
- Every dabcheck LLM call is restricted to the agent's model (`LLM(allowed_models=...)`) and capped in dollars
  (`--budget` for preprocessing, `DABCHECK_VERIFY_BUDGET` for the verifier, default $10 per sweep).
- Runs, archives and preprocessing outputs live under `$DAB_SCRATCH` (`/scratch/.../minhyeok`), because /home is near its quota.

Deviations from the papers (in addition to those in `docs/dabcheck.md`)
- FDJ: when the cross product exceeds `--max-cross` and the scaffold has no exact hash-join block, the
  scaffold is evaluated on blocked candidates (top-k character-trigram matches per left value) instead of
  the cross product; when more than `--max-refine` candidates remain, they are delivered unrefined and the
  README says so. Sparse joins top up training positives from the same trigram candidates (logged).
- FDJ self-joins (duplicate records) are delivered as connected components of the match graph.
- sqlverify: the verifier sees one database's schema; DAB answers often combine several databases in Python.
- sqlverify selection step: the paper verifies the SQL that answers the question. In the first pilot
  (stockindex q1, answer correct) the agent's SQL were fetch/inspect statements finished in pandas, and all three
  were rejected against the whole question, which would send correct answers to a second round. Only statements an
  LLM judges answer-level are verified now; a run with none is accepted without a second round.

Commands (Great Lakes, from the repository root)

    strict/.venv/bin/python -m pytest tests -q
    strict/.venv/bin/python -m dabcheck.prep --method fdj    --out $DAB_SCRATCH/dab-prep --dry-run
    strict/.venv/bin/python -m dabcheck.prep --method docetl --out $DAB_SCRATCH/dab-prep --dry-run
    strict/.venv/bin/python -m dabcheck.prep --method docetl --out $DAB_SCRATCH/dab-prep --budget 5      # in a Slurm job
    strict/.venv/bin/python -m dabcheck.prep --method fdj    --out $DAB_SCRATCH/dab-prep --budget 8
    strict/.venv/bin/python native104.py --submit --pilot --harness claude --trial 1 --method sqlverify
    strict/.venv/bin/python native104.py --submit --harness claude --trial 1 --method fdj   # then docetl, sqlverify, trial 2
