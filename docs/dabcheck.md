# dabcheck: design notes and how to run

`dabcheck` is a Python package (3.12, dependencies in `requirements.txt`) with three modules, a CLI,
offline tests, and experiments on the DataAgentBench data. Every LLM call goes through
`dabcheck.llm.LLM` (Anthropic Messages API, disk cache, usage accounting); `MockLLM` has the same
interface and drives all tests. No API key is needed for the tests or the experiments.

```
python -m pytest tests -q                     # 37 tests, mock LLM only
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

Checked against the authors' code (github.com/szeighami/FDJ, `fdj/create_fd/*.py`, `fdj/utils/prep_data.py`).

| Paper / reference | Code | Notes |
|---|---|---|
| featurization (d, X_L, X_R), predicates d(X_L(l), X_R(r)) <= theta, CNF | `featurize.Featurization`, `cnf.Scaffold` | distances in `distances.py`; the reference uses one distance (embedding cosine) and LLM extractors only; `register_distance` adds embeddings |
| sampling (reference `get_suffiecient_positives`, `get_train_with_negatives`) | `join.sample_training_pairs` | uniform pairs labelled in batches of 100 until 250 positives; negatives completed to 1500; the first 50 positives / 100 negatives drive discovery, the rest set thresholds. The reference does not label the extra random negatives (`label_random_negatives=False` reproduces that); the paper labels everything (default). `candidates_fn` tops up positives only when the uniform budget is exhausted (logged) |
| initial `sem_sim` featurization | `join.raw_similarity_featurization` | token-Jaccard stand-in for embedding similarity when no embedding distance is registered |
| Alg. 2 generation: walkthrough of the examples, descriptions, per-column operations, the second column told the first column's format | `featurize.walkthrough`, `generate_featurizations`, `_make_extractor(other_spec=...)` | one feature per generation call as in the reference (`max_rules = 1`); the paper's separate "code or LLM?" decision is folded into the extractor call, which returns `{mode, code, prompt, output_format}` |
| code vs LLM extractors | `CodeExtractor`, `LLMExtractor` | generated code runs with a restricted builtins table and a guarded `__import__`; this is a guard against mistakes, not a security sandbox |
| Eq. 1 cost to cover, Alg. 3 evaluate-and-pick-examples, stop when the costliest positive < alpha (`max_cost = 10`) | `featurize.cost_to_cover`, `evaluate_and_pick_examples` | negatives shown to the LLM are those that beat a selected positive (paper Alg. 3); the reference shows random negatives |
| Alg. 1 iterative candidate generation | `featurize.get_candidate_featurizations` | max_iter = 4 |
| Eq. 2 cost, Alg. 4 scaffold | `cnf.best_thresholds`, `cnf.build_scaffold` | `cost_mode='fpr'` is the paper's F_S = FP / (TP + FP); `cost_mode='neg'` is the reference's FP / |S_n|. Candidate thresholds are the (max_miss + 1) largest positive distances for singleton clauses (reference pruning); exhaustive grid when small, coordinate descent otherwise. gamma: reference 0.2 of the negatives; default here 0.1 on the FPR scale. The disjunction loop restarts after every addition as in the reference |
| Sec. 6.3 adjusted target T' | `cnf.adjusted_target_single` (one predicate: the reference's exact binomial test, smallest r/k with P(Bin(k, T) >= r) < delta), `cnf.adjusted_target_high_dim` (several predicates: the reference's worst-case Monte Carlo bound ported single-process with 1000 trials, n_max from the Hoeffding estimate; falls back to the binomial bound with delta / d when the simulation finds no attainable threshold) | the paper's Thm. 6.1 proof is in its technical report |
| Alg. 5 FDJ, refinement with L_p | `join.fdj_join` | `labeler` can be the LLM (`llm_labeler`) or any oracle; `target_feasible=False` reports that no thresholds reached T' on the threshold sample |
| precision target T_P < 1 (Sec. 7.1) | not implemented | we keep T_P = 1 as the paper and the reference do |

`audit_join` is our addition for data agents: match statistics under several canonicalisation rules
plus warnings (rule swing, zero-padded ids, `#` prefixes, unmatched rows, fan-out). It accepts a
`{key: count}` dict for large tables; the first rule is the baseline.

### `dabcheck.extract` -- DocETL (VLDB 2025, Shankar et al.)

Checked against github.com/ucbepic/docetl (`operations/map.py`, `reduce.py`, `resolve.py`, `operations/utils/api.py`,
`optimizers/map_optimizer/*`).

| Paper | Code | Notes |
|---|---|---|
| map / parallel map / filter with schema type checks, Python validations, retry with the failure context, drop after `retries` (Sec. 2.1-2.2) | `ops.map_op`, `validate_output_types`, `parallel_map`, `filter_op` | the retry appends the failed answer and the failure to the conversation (DocETL `api.py`); `parallel_map` runs every prompt against the original document |
| reduce with batched folding and scratchpad (Sec. 2.2.2, Fig. 2) | `ops.reduce_op` | DocETL contract: `fold_prompt` sees `{{ inputs }}`, `{{ output }}` (also `{{ accumulated }}`), `{{ reduce_key }}`; `updated_scratchpad` is null unless counts/lists span batches; a group that fits one batch is not folded; list-valued keys become tuples; no merge step (`associative`) |
| resolve: blocking, pairwise comparison prompt, union of matches, resolution prompt per cluster (Sec. 2.2.3) | `ops.resolve` | DocETL blocks with embedding similarity auto-tuned to 95% recall or Python conditions; here the block is token similarity (`blocking_threshold`) and `blocking_conditions`, every surviving non-identical pair goes to the comparison prompt |
| unnest / split / gather (Sec. 2.3) | `ops.unnest`, `split`, `gather` | DocETL's chunk-size and peripheral-context search is not implemented |
| gleaning, directive (7) (Sec. 3.2.1, Fig. 4) | `gleaning.glean` | as in DocETL: validator messages = original prompt + the answer as an assistant turn + validation instruction -> `{should_refine, improvements}`; the refinement call carries the full history; default 2 rounds |
| chaining (10), isolating (11) | `optimizer.rewrite_map` | step schemas are derived from `output_keys` and the original schema; isolating adds uncovered keys to the last subtask, chaining ends with the full schema |
| validation agent, gate, ratings, pairwise comparison, opportunistic optimisation (Sec. 4) | `optimizer.synthesize_validation` (criteria written from a sample input/output), `needs_improvement` (boolean gate over up to 3 samples), `rate_outputs`, `optimize_map` (top 6, one win per pair) | DocETL rates on a 4-category scale; here 1-5 |
| not implemented | Jinja2 templates (`render` supports `{{ a.b }}` only), chunk-size / fold-batch search, header lineage, embedding blocking, pre-aggregation and pre-joining directives, YAML DSL, parallel execution |

`extract.pipeline.extract_values` is the DAB-specific plan: code first (`numbers.parse_amount`,
`find_numbers`, regex specs), `coverage.coverage_report` (coverage, per-pattern counts, truncation
signal, unparsed samples), LLM map with an *evidence* field that must be a verbatim substring
consistent with the value, one gleaning round, final coverage warning.

### `dabcheck.sqlverify` -- Text-to-SQL verification (VLDB 2026, Alrashed et al.)

| Paper | Code |
|---|---|
| SC direct critique (Sec. 3.1) | `critique.sql_critique` |
| RT round trip: R(s, d) isolated from q, C(q, q') Likert 1-5, tau = 4 (Sec. 3.2) | `roundtrip.back_translate`, `critique_questions`, `round_trip_verify` |
| SE synthetic execution, answer-first and data-first; comparison with inner and outer sorting, or inner sorting only when the query has ORDER BY (Sec. 3.3, 4.2) | `synthexec.synthesize_cases`, `execute_sql` (in-memory sqlite; postgres/duckdb SQL transpiled with sqlglot, which is required for those dialects), `results_match(ordered=has_order_by(sql))`, `synthetic_execution_verify` |
| AND / OR combinations (Sec. 5.2.4), selective generation (Sec. 7) | `verify.verify_sql`, `verify.selective` |
| our addition | `cohort.cohort_check`: intent cards for q and s, deterministic time-window / date-field / as-of / limit checks, LLM field-by-field verdicts |

The paper's artifact (figshare private link) could not be downloaded from the cluster, so prompts
follow the paper text (zero-shot variants; the paper reports few-shot as slightly more permissive).
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
- `cve_fdj.md`: oracle (DAB corruption code + KEV notes) reproduces q3 = 1262; FDJ T = 0.9, delta = 0.1 with
  hand-written code features: CNF `(digit_stream_edit <= 12 OR family_decoders <= 0)`, recall 0.991,
  precision 1.000, but refinement still touches ~97% of the cross product because the hand-written
  features are weak -- feature quality, which the LLM generation loop supplies, is what buys the cost reduction.
- `crm_sql_verify.md`: signed-date vs created-date SQL give different agents on the real data; synthetic
  execution accepts the former and rejects the latter; intent cards flag the date field.
