# dabcheck: design notes and how to run

`dabcheck` is a Python package (3.12, dependencies in `requirements.txt`) with three modules, a CLI,
offline tests, and experiments on the DataAgentBench data. Every LLM call goes through
`dabcheck.llm.LLM` (Anthropic Messages API, disk cache, usage accounting); `MockLLM` has the same
interface and drives all tests. No API key is needed for the tests or the experiments.

```
python -m pytest tests -q                     # 32 tests, mock LLM only
python experiments/exp_deps_extraction.py     # needs ~/DataAgentBench (DAB_ROOT) with the data downloaded
python -m dabcheck audit-join sqlite:/path.db id sqlite:/path2.db ref --left-table t1 --right-table t2
python -m dabcheck extract duckdb:/project_query.db Project_Information --table project_info --name forks \
       --pattern '(?P<value>\d{1,3}(?:,\d{3})+|\d+)\s+forks?' --parse int --no-llm
python -m dabcheck verify-sql --question "..." --sql query.sql --schema duckdb:/sales_pipeline.duckdb   # needs a key
```

API key (only for `verify-sql`, `fdj`, LLM extraction): `ANTHROPIC_API_KEY` or `~/.config/dab/anthropic_key`
(mode 600). Models: `DABCHECK_MODEL` (default `claude-sonnet-5-5`: featurization generation, critiques,
synthetic data) and `DABCHECK_CHEAP_MODEL` (default `claude-haiku-5-5`: per-row extraction and pair labels).
Replies are cached under `~/.cache/dabcheck`, so re-running an experiment does not spend again.

## Module map and paper fidelity

### `dabcheck.fdj` -- Featurized-Decomposition Join (VLDB 2026, Zeighami et al.)

| Paper | Code | Notes |
|---|---|---|
| featurization (d, X_L, X_R), predicates d(X_L(l), X_R(r)) <= theta, CNF | `featurize.Featurization`, `cnf.Scaffold` | distances in `distances.py` (exact, numeric, date, token Jaccard, set overlap, edit, digit edit, prefix); `register_distance` adds embeddings |
| Alg. 2 get-featurization-from-examples | `featurize.generate_featurizations` | one LLM call for descriptions, one per side for the extractor (the paper splits "describe", "code or LLM?", "write" into separate calls; here one call returns `{mode, code, prompt}`), one for the distance |
| code vs LLM extractors | `CodeExtractor`, `LLMExtractor` | generated code runs with a restricted builtins table and only `re/json/math/datetime/collections/itertools/string` imports; this is a guard against mistakes, not a security sandbox |
| Eq. 1 cost to cover, Alg. 3 evaluate-and-pick-examples | `featurize.cost_to_cover`, `evaluate_and_pick_examples` | alpha = 10, beta = 20 as in the paper |
| Alg. 1 iterative candidate generation | `featurize.get_candidate_featurizations` | max_iter = 4 |
| Eq. 2 cost hat C_S, Alg. 4 scaffold | `cnf.best_thresholds`, `cnf.build_scaffold` | exhaustive threshold grid when small, coordinate descent otherwise; the first conjunct is admitted on a cost tie so a disjunction can grow from the trivial scaffold (tested) |
| Sec. 6.3 thresholds at T' > T | `cnf.set_thresholds`, `adjusted_recall_target` | T' = T + z_delta * sqrt(T(1-T)/n_pos) (one-sided normal bound); the paper's Thm. 6.1 form is in its technical report |
| Alg. 5 FDJ, refinement with L_p | `join.fdj_join` | `labeler` can be the LLM (`llm_labeler`) or any oracle; `candidates_fn` tops up the labelled samples with positives when the join is too sparse for uniform sampling (a documented deviation) |
| precision target T_P < 1 (Sec. 7.1) | not implemented | we keep T_P = 1 as the paper does in its experiments |

`audit_join` is our addition for data agents: match statistics under several canonicalisation rules
plus warnings (rule swing, zero-padded ids, `#` prefixes, unmatched rows, fan-out). It accepts a
`{key: count}` dict for large tables.

### `dabcheck.extract` -- DocETL (VLDB 2025, Shankar et al.)

| Paper | Code |
|---|---|
| map / parallel map / filter with Python validations and retry (Sec. 2.1-2.2) | `ops.map_op`, `parallel_map`, `filter_op` |
| reduce with batched folding and scratchpad (Sec. 2.2.2, Fig. 2) | `ops.reduce_op` |
| resolve with blocking + pairwise comparison + canonical value (Sec. 2.2.3) | `ops.resolve` (blocking by token similarity; union-find; LLM or most-frequent canonical) |
| unnest / split / gather (Sec. 2.3) | `ops.unnest`, `split`, `gather` |
| gleaning, directive (7) (Sec. 3.2.1, Fig. 4) | `gleaning.glean` |
| chaining (10), isolating (11) | `optimizer.rewrite_map` |
| validation agents, ratings, pairwise comparison, opportunistic optimisation (Sec. 4) | `optimizer.synthesize_validation`, `rate_outputs`, `optimize_map` (top-k = 3 instead of 6) |
| not implemented | chunk-size / fold-batch search, header lineage, embedding blocking, pre-aggregation and pre-joining directives, YAML DSL |

`extract.pipeline.extract_values` is the DAB-specific plan: code first (`numbers.parse_amount`,
`find_numbers`, regex specs), `coverage.coverage_report` (coverage, per-pattern counts, truncation
signal, unparsed samples), LLM map with an *evidence* field that must be a verbatim substring
consistent with the value, one gleaning round, final coverage warning.

### `dabcheck.sqlverify` -- Text-to-SQL verification (VLDB 2026, Alrashed et al.)

| Paper | Code |
|---|---|
| SC direct critique (Sec. 3.1) | `critique.sql_critique` |
| RT round trip: R(s, d) isolated from q, C(q, q') Likert 1-5, tau = 4 (Sec. 3.2) | `roundtrip.back_translate`, `critique_questions`, `round_trip_verify` |
| SE synthetic execution, answer-first and data-first, order-insensitive comparison (Sec. 3.3, 4.2) | `synthexec.synthesize_cases`, `execute_sql` (in-memory sqlite; postgres/duckdb SQL transpiled with sqlglot), `results_match`, `synthetic_execution_verify` |
| AND / OR combinations (Sec. 5.2.4), selective generation (Sec. 7) | `verify.verify_sql`, `verify.selective` |
| our addition | `cohort.cohort_check`: intent cards for q and s, deterministic time-window / date-field / as-of / limit checks, LLM field-by-field verdicts |

Schemas come from `schema_from_sqlite`, `schema_from_duckdb`, or `schema_from_ddl` (hand-written DDL
or a pg_dump header). The DAB PostgreSQL dumps can be loaded into sqlite with `dabcheck.util.pgdump`.

### Harness integration

- `native104.py --checks` (needs `--trial`): stages the package in each task's working directory and
  appends `dabcheck/AGENT_INSTRUCTIONS.md` to the prompt; the run is labelled condition
  `description+hints+checks` and written to `<tag>-checks-104x3/trialN`. The sandbox has no network,
  so only the code-only checks run inside it.
- `dabcheck.harness.post_run_verify(folder, question, schema, llm)`: recovers SQL from
  `events.jsonl` (Codex and Claude Code formats), verifies the last queries with the chosen
  methods, writes `checks.json`; `continue_with_warnings` builds the message for a second round.

## Offline validation results

Produced by `experiments/*.py` on the pinned DataAgentBench data (`experiments/results/*.md`):

- `imdb_join_audit.md`: keyword.id vs movie_keyword.keyword_id -- raw 0 matched keys, numeric_id 134,170;
  q10 keyword filter 2,371 vs 21,046 movies; two warnings fire.
- `deps_extraction.md`: naive regex 67% coverage with 18 truncations (material-ui 522); pipeline 100%
  coverage, all five q2 ground-truth fork counts exact.
- `usaspending_amounts.md`: 681 of 10,266 amount rows are exact formats (6.6%); coverage warning fires.
- `cve_fdj.md`: oracle (DAB corruption code + KEV notes) reproduces q3 = 1262; FDJ T = 0.9, delta = 0.1:
  recall 0.988, precision 1.000, but the feasible predicate is `digit_stream_edit <= 16`, so refinement
  costs ~99% of the cross product -- feature quality, not the CNF, is what the LLM loop must supply.
- `crm_sql_verify.md`: signed-date vs created-date SQL give different agents on the real data; synthetic
  execution accepts the former and rejects the latter; intent cards flag the date field.
