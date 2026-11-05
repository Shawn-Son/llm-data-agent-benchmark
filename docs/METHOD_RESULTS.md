# Results: one paper method per failure category, Haiku only (November 5, 2026)

Setup: the 104 DataAgentBench questions, descriptions + hints, unchanged original validators, Claude Code with
`claude-haiku-5-5` as the agent and as every LLM inside the methods. One trial per method condition (trial 2 was
cancelled for time); the baseline is the two existing Haiku trials. Design and deviations: `docs/EXPERIMENTS.md`.
Tables: `results/method-comparison/COMPARISON.md` (`python experiments/compare_methods.py`).

## Headline numbers

| Condition | Correct / 104 | Agent cost | Method LLM cost |
|---|---|---|---|
| Haiku baseline, trial 1 / trial 2 | 66 (63.5%) / 63 (60.6%) | $3.12 / $4.31 | - |
| fdj (identifier joins) | 61 (58.7%) | $3.27 | $14.72 preprocessing |
| docetl (extraction) | 67 (64.4%) | $2.61 | $1.39 preprocessing |
| sqlverify (cohort / temporal) | 71 (68.3%); round 1 alone 69 (66.3%) | $3.52 | $0.14 verifier |

The headline differences are mostly run-to-run noise, not method effects. Each method touched only part of the
benchmark; on the questions it did not touch (baseline prompt, no intervention) the single trial differs from the
baseline trials by -1 to +6 correct answers:

| Condition | Acted on | Correct there (condition / baseline t1 / t2) | Untouched | Correct there (condition / baseline t1 / t2) |
|---|---|---|---|---|
| fdj | 23 (civic, usaspending, music_brainz) | 8 / 12 / 9 | 81 | 53 / 54 / 54 |
| docetl | 22 (DEPS, cve, usaspending) | 6 / 7 / 7 | 82 | 61 / 59 / 56 |
| sqlverify | 9 (second round ran) | 8 / 6 / 6 | 95 | 63 / 60 / 57 |

## Per method

**FDJ (identifier joins): no gain with Haiku; it hurt where it acted.**
- All four cve joins (the main identifier-join category) hit their dollar cap during pair labelling and delivered
  nothing; Haiku labels cost about 330 output tokens each, so $2.5 per spec bought too few labels.
- The usaspending joins and the music_brainz duplicates produced more candidate pairs than the refinement cap
  (3,000), so they were delivered unconfirmed: ~10 candidate contracts per award id. On the 23 questions that
  received FDJ outputs the condition got 8 right versus 12 and 9 in the baseline; usaspending q8 (right in both
  baseline trials) was lost. civic project-name clustering (58 pairs, confirmed) did not change civic accuracy.

**DocETL (extraction): one targeted fix, no net change where it acted.**
- DEPS q2, wrong in both baseline trials because `(\d+) forks` truncated "30,522 forks", was right; the agent cross-
  checked its own parse against the extracted column. DEPS q1 still failed on an interpretation choice (stars were right).
- usaspending `amount_text`: Haiku returned null for all 9,585 prose amounts (they state vague magnitudes, contrary
  to the hint), so the column kept the 6.6% code coverage and the usaspending questions did not move.
- On the 22 questions with DocETL outputs: 6 right versus 7 and 7.

**Text-to-SQL verification (cohort / temporal): small positive effect, through a narrow window.**
- DAB agents fetch rows with SQL and compute in Python: of 104 runs, 101 ran single-database SQL but only 9 ran SQL
  that an LLM judged answer-level (the selection step added after the pilot; without it every fetch query was rejected).
- All 9 were rejected (RT + SE + cohort, AND): 3 true rejects, 6 false rejects. Several rejected statements were
  Python templates (`{ids}`, `%s`) recovered from the agent's code, which the verifier cannot evaluate.
- Second round: wrong -> right 2 (music_brainz q1, q3), right -> right 6, wrong -> wrong 1, right -> wrong 0.
  The net method effect is +2 questions; the remaining gap to the baseline (round 1: 69 correct) is noise.
- The cohort/temporal questions it targets (crmarenapro q12, civic as-of questions) never reached a verifiable SQL
  statement; crmarenapro q12 stayed wrong.

## What this supports

- None of the three methods, as applied to a multi-step agent, acts on most of the failures it targets: FDJ and DocETL
  are configured before the run and only help if the agent uses their outputs; the SQL verifier only sees a final SQL
  statement, which DAB agents rarely write.
- With Haiku as the method LLM, FDJ did not reach a usable join on the hardest key families (cve) within $15.
- One trial per condition cannot separate effects of +-5 questions from noise; per-question comparisons above are
  the more reliable signal.

## Where everything is

- Committed: per-question method fields (`results/haiku-claude-<method>-104x3/trial1/method_runs.csv`), metrics,
  per-dataset tables, archive records, `verify_summary.json` (sqlverify), `results/method-prep/<method>/summary.json`.
- On Great Lakes scratch (`/scratch/cse584f26_class_root/cse584f26_class/minhyeok`): full trajectories and graded runs
  (`dab-artifacts/`), verified archives (`dab-archives/`, checksums in each `ARCHIVE.json`), preprocessing CSVs (`dab-prep/`).
  Scratch is purged after 60 days without access.
