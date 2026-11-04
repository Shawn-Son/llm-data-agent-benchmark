# Proposal: verification modules for data agents on DataAgentBench

*Written for the CSE 584 project team. Status: implementation and offline validation done on branch `verify-modules`; live runs need an API key.*

## 1. Where we stand

The reproduction in this repository (terra x2, Haiku x2, 104 questions) ends with a trajectory-level
failure review of 166 wrong runs ([results/failure-review/FAILURE_REVIEW.md](../results/failure-review/FAILURE_REVIEW.md)).
Three mechanisms account for most questions that a model gets wrong in both of its runs:

| Failure mechanism (review category) | terra both-wrong | Haiku both-wrong | Typical case |
|---|---:|---:|---|
| Identifier joins and identity (J1, J2, J5) | 7 / 36 | 8 / 32 | cve q8: digit-subsequence matching gives 244 vs 58; imdb q10: digit strings with leading zeros keep 119 of 937 movies |
| Extraction and representation (E1, E2, E3) | 7 / 36 | 3 / 32 | DEPS q2: `(\d+) forks` turns 30,522 into 522; usaspending: prose amounts |
| Cohort / temporal (C1, T1, T2, T4) | 15 / 36 | 8 / 32 | crmarenapro q12: created date instead of signed date (all four runs); civic q4/q6: no as-of join; PANCANCER q3: restricted denominator |

Our earlier pilot on the 54-question release (CSE 584, October 2026) measured *silent join errors*
narrowly (fan-out, dropped rows) and found them to be the primary cause of only 4% of failures. The
review above widens the lens: the failures are not SQL-level accidents but wrong *decoding*, wrong
*parsing* and wrong *intent*. The proposal therefore changes from "SQL warnings" to three
verification modules, each taken from a recent VLDB paper that solves exactly one of the three mechanisms.

## 2. The three modules (implemented in [`dabcheck/`](../dabcheck))

**Identifier joins -> FDJ** (Zeighami, Shankar, Parameswaran, *Featurized-Decomposition Join*, VLDB 2026).
Joins across representations are rewritten as cheap feature comparisons: an LLM proposes feature
extractors (code when possible) and distance functions from labelled example pairs, a cost-to-cover
loop picks the pairs the current features cannot separate, a CNF of thresholded predicates is built
greedily to minimise false positives at a recall target, thresholds are set on a fresh sample so the
recall target holds with probability 1 - delta, and every candidate pair is confirmed by the LLM
(precision 1). `dabcheck.fdj` implements Alg. 1-5 and adds `audit_join`, an LLM-free check that
reports how the match count swings with the key rule (raw / strip `#` / integer id / OCR fold) and
warns about zero-padded ids, unmatched rows and fan-out.

**Extraction -> DocETL** (Shankar et al., VLDB 2025). Single-prompt extraction misses instances;
DocETL rewrites the operation (chaining, isolating, split-gather, gleaning = validator + refinement
rounds, resolve for entity canonicalisation, folded reduce) and uses validation agents to pick the
plan. `dabcheck.extract` implements the operators, gleaning, resolve, the optimizer loop, and a
code-first pipeline for the DAB case: regex/number parsers first (exact formats, thousands
separators, "$1.5M", word amounts, sum-of-parts), a *parse-coverage report* that fires when
rows stay unparsed or captures look truncated, then an LLM map with evidence validation only on
the rows code could not parse.

**Cohort / temporal -> Text-to-SQL verification** (Alrashed, Sukoon, Karger, Noy, VLDB 2026). A
verifier V(q, s, d) decides without ground truth whether SQL s answers question q: *round-trip
critique* (back-translate s to a question with no access to q, then a 1-5 Likert comparison,
accept at >= 4), *synthetic execution* (the LLM builds small test databases with known answers,
s is executed on them) and the direct-critique baseline; AND-combination has the lowest false-accept
rate; a rejected query becomes an abstention or a retry. `dabcheck.sqlverify` implements all three
and adds a *cohort check*: question and SQL are each reduced to an intent card (population, filters,
event date field, time window with inclusive end, as-of rule, aggregate, denominator, ranking,
output) and compared field by field, with deterministic date-window and date-field checks.

## 3. What has been validated without an API key

All 37 unit tests run with a scripted mock LLM (`tests/`), including the FDJ paper's Fig. 6 scaffold
example, gleaning with validator feedback, folded reduce with a scratchpad, resolve, and the
right/wrong SQL pair of crmarenapro q12 through synthetic execution. The offline experiments in
`experiments/` use the real DAB data:

| Experiment | Result |
|---|---|
| imdb keyword join audit | raw key equality matches 0 keys, integer ids match all 134,170; the q10 keyword filter links 2,371 movies under the digit-string rule and 21,046 under the integer rule; warnings fire without an LLM |
| DEPS fork/star extraction | naive `(\d+) forks`: 67% coverage, 18 truncation signals, 522 for material-ui; the pipeline: 100% coverage and all five q2 ground-truth fork counts exact |
| usaspending amount_text | code parses 6.6% of rows (681 of 10,266); the coverage warning says the answer would rest on a subset before any aggregation |
| cve KEV-vulns join (oracle from DAB's own corruption code) | the oracle reproduces q3 exactly (1262); FDJ with hand-written features builds `(digit_stream_edit <= 12 OR family_decoders <= 0)` and reaches recall 0.991 >= 0.9 at precision 1, but refinement still touches 97% of pairs: the LLM feature-generation loop is what buys the cost reduction |
| crmarenapro q12 SQL verification | the signed-date and created-date queries name different agents on the real data; synthetic execution accepts the signed-date query and rejects the created-date one; intent cards flag the date-field mismatch |

## 4. Evaluation plan (needs an API key; estimated < $40 with Haiku for agents and Sonnet for verifiers)

Conditions, same 104 questions, unchanged validators, separate trial directories:

- **A. baseline**: existing runs (terra x2, Haiku x2).
- **B. checks in the prompt** (`native104.py --harness claude --trial N --checks`): the code-only
  tools (`audit_join`, `extract_values`, `execute_sql`) are staged in the task directory and the
  agent instructions appended. No LLM calls inside the sandbox.
- **C. post-run verify and respond**: after a run, `dabcheck.harness.post_run_verify` recovers the
  SQL the agent executed from the event log, runs round-trip + cohort + synthetic execution outside
  the sandbox, and a second agent round receives the warnings (`continue_with_warnings`).
- **D. FDJ as a tool**: for the cve and usaspending questions only, the FDJ join is run once per
  table pair with `generate=True` and the agent receives the decomposition.

Metrics: accuracy per condition and per review category; for the verifiers, false-accept / false-reject
rates on the 166 wrong and 243 scored runs we already have (the review's labels are the reference);
coverage vs selective accuracy when a rejection becomes an abstention; token cost per question.

## 5. Risks and limits

- The agent sandbox has no network: LLM-backed checks can only run harness-side (condition C).
- Verifier errors: the paper reports FAR 0.40-0.66 / FRR 0.16-0.31 per method; AND-combination
  trades coverage for accuracy. We should expect some correct answers to be flagged.
- FDJ needs labelled positives; at DAB's key density a uniform sample is too sparse, so the sample is
  enriched (documented in `experiments/exp_cve_fdj.py`), which is a deviation from the paper's sampling.
- Hints already tell the agent what to do (imdb, crmarenapro); the checks help where the agent
  ignores them or the hint is wrong (usaspending).

## 6. Division of work (proposal)

1. Run condition B on Haiku (one trial) and compare per category.
2. Run condition C on the existing event logs first (no agent re-runs) to measure verifier FAR/FRR.
3. Run FDJ with `generate=True` on cve (KEV x vulns) and report cost ratio and recall against the oracle.
4. Write up: which category moved, at what token cost, and the verifier confusion matrix.
