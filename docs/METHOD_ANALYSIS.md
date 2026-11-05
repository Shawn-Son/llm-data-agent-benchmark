# Detailed analysis: do the three paper methods fix the failures they target? (Haiku, November 5, 2026)

Companion to `docs/METHOD_RESULTS.md` (numbers) and `docs/EXPERIMENTS.md` (design). Evidence comes from the
graded runs and from the agents' trajectories (`experiments/analyze_method_traces.py`, run on Great Lakes;
trajectories are in the scratch archives listed in each `ARCHIVE.json`).

## 1. Findings

1. **No method produced a correct answer that can be attributed to its outputs, except a second look in sqlverify.**
   Across 54 method-touched questions, the only wrong-to-right changes caused by a method are two second rounds of
   sqlverify (music_brainz q1, q3), and the verifier's warnings in both were about Python-templated SQL, not about
   the actual mistake.
2. **The headline accuracy differences are noise.** Untouched questions received the baseline prompt byte for byte
   (checked by SHA-256 against baseline trial 1: 81/81 fdj, 82/82 docetl, 95/95 sqlverify), yet the single trials
   differ from the baseline trials by -1 to +6 correct answers on them. Three questions that Haiku got wrong in both
   baseline trials were right in all three new runs without any intervention (crmarenapro q13, krama q4,
   stockmarket q4); DEPS q2 and cve q6 were also right in the fdj run, which delivered nothing for those datasets.
3. **Agents read the method outputs and mostly declined to use them.** In every staged question the agent opened
   `dabcheck_prep/README.md`; it loaded an output file with code in 31 of 45 (fdj 20/23, docetl 11/22; a pattern
   match on tool inputs). The final answers say why they did
   not rely on them: FDJ clusters "merge genuinely different projects", the FDJ award join "links each award to about
   10 candidates", the DocETL amount file "added nothing" or held wrong values, the CVSS file "doesn't help with the
   ID join".
4. **The methods' outputs were weak with Haiku, and in one case wrong.** FDJ delivered nothing for cve (all four joins
   hit the dollar cap) and unconfirmed top-10 candidates for usaspending awards. DocETL's LLM step added no amounts,
   and its code-first parser turned 159 vague sentences into false amounts (fixed after the run, see section 5).

## 2. Noise floor

| Question | Baseline t1 / t2 | fdj | docetl | sqlverify | Method acted? |
|---|---|---|---|---|---|
| crmarenapro q13 | wrong / wrong | right | right | right | no (all three) |
| krama q4 | wrong / wrong | right | right | right | no |
| stockmarket q4 | wrong / wrong | right | right | right | no |
| DEPS_DEV_V1 q2 | wrong / wrong | right (no DEPS outputs) | right (outputs staged) | wrong | docetl only |
| cve q6 | wrong / wrong | right (cve outputs empty) | wrong | wrong | no effective output |

The three questions fixed by every new run share nothing but the run date (all new runs: November 5; same Claude
Code 2.1.317, same harness code paths for untouched questions). With one trial per condition, any single-question
change has to be checked against this table before it is credited to a method.

## 3. FDJ (identifier joins and identity)

**What was delivered** (`results/method-prep/fdj/summary.json`, $14.72 of Haiku calls, 74,766 calls)

| Join | Result | Quality |
|---|---|---|
| cve: kev, cvss, descriptions, cpe -> vulns | failed, dollar cap during pair labelling | nothing delivered; cve prompt = baseline |
| usaspending award ids (amounts -> contracts) | 97,422 pairs, unconfirmed | 8,555 of 9,921 award ids have 10 candidates; e.g. `fa945323f0006` -> `FA945323-F-0016`, `FA945322C0011`, ... |
| usaspending award ids (documents -> contracts) | 56,190 pairs, unconfirmed | 3,944 ids with exactly one candidate, 3,805 with ten |
| usaspending recipient UEIs | 3,317 pairs, 1:1 | identity pairs (`uei:c12nsyah27n4` -> `uei:c12nsyah27n4`) |
| music_brainz duplicate tracks | 10,492 clusters / 19,375 records, unconfirmed | 5,825 singletons; clusters up to 12 records |
| civic project names | 59 clusters / 99 names, confirmed | correct merges (`citywide_guardrail_replacement` = `guardrail_replacement_citywide`) next to wrong ones (`outdoor_warning_signs` + `pch_overhead_warning_signs`, `2021_annual_street_maintenance` + `2022_annual_street_maintenance`) |

Why the cve joins failed: every cap was reached in pair labelling (`fdj.label`). A Haiku label averaged about 350
output tokens (26.4M output tokens over 74,766 calls; reasoning tokens count), about $0.0002, so each $2.5 join
budget paid for roughly 12,000 labels. A uniform pair sample finds almost no matches (one true partner among 75,199
vulns keys), so FDJ has to label blocked candidates to collect its 250 training positives, and with 32 noisy key
encodings few trigram candidates are true matches. The earlier live test (`docs/LIVE_HAIKU_RESULTS.md`) already
showed Haiku generating no separating feature for these keys.

**How agents used it (23 questions with FDJ outputs)**: 8 right versus 12 and 9 in the baseline.

| Question | Result (fdj / base t1 / t2) | What the agent did with FDJ |
|---|---|---|
| civic q1, q8 | right / right / right | used clusters as a reference, overrode PCH Median merge |
| civic q2, q3, q5, q6, q7 | wrong / wrong / wrong | q6: "the FDJ cluster file merges genuinely different projects"; q5: overrode clusters; still wrong |
| civic q4 | wrong / right / wrong | "matched funding names to agenda titles by hand, using the FDJ clusters as a guide" (0.29 vs 0.34) |
| civic q9 | right / right / wrong | "did not take the precomputed FDJ clusters at face value" |
| civic q10 | wrong / right / wrong | "did not accept the FDJ clusters blindly" (0.63 vs 0.69) |
| music q1 | wrong / wrong / wrong | FDJ cluster agreed with its own grouping; answer $601.44 vs $1,059.46 (missed records) |
| music q2 | right / right / right | FDJ cluster matched its own comparison |
| music q3 | right / right / right | "I checked the FDJ duplicate clusters and they are unreliable" |
| usaspending q1, q5, q6, q9 | wrong / wrong / wrong | did not use FDJ; q5: exact one-to-one award match found without it |
| usaspending q2 | wrong / right / wrong | used the FDJ recipient map; rejected the award join ("about 10 candidates") |
| usaspending q3, q7, q10 | right / right / right | q3 cross-checked the recipient map with a deterministic key; q7: award join "isn't usable as a join" |
| usaspending q4 | wrong / wrong / right | "the FDJ amounts-to-contracts file is unreliable here" |
| usaspending q8 | wrong / right / right | "stripping non-alphanumeric characters and uppercasing gave an exact match for all 10,266 amount rows, so I did not need the precomputed FDJ joins" |

Takeaways: the identifier problems FDJ targets in usaspending are solvable by a deterministic canonicalization the
agent found itself (q5, q8), so an approximate semantic join adds noise there; where keys are truly hard (cve), FDJ
with Haiku delivered nothing. The cases where the outputs were consulted and the answer got worse (civic q4/q10,
usaspending q2) are each one trial against a baseline that was itself 1/2 on them, so harm is possible but not shown.

## 4. DocETL (extraction and representation)

**What was delivered** ($1.39; `results/method-prep/docetl/summary.json`)

| Column | Rows | Source of values |
|---|---|---|
| DEPS `Project_Information` -> name, stars, forks | 770 | code 769-770, LLM 1 (one stars value) |
| cve `score_text` -> CVSS score | 68,367 | code 100% |
| usaspending `amount_text` -> amount | 10,266 | code 681, none 9,585 (LLM returned null for every prose row) |
| usaspending recipient / agency totals | 3,317 / 47 | code 100% |

The prose amounts state magnitudes only ("hovering in the six-figure range", "a ten-figure commitment"), so the
LLM's null is correct behaviour; the hint's claim that every format encodes an exact amount is false for these rows.
**Defect found in the trajectories**: 159 of the 681 code values came from digit-free prose (a stray "million" ->
1,000,000, a company name "FOUR POINTS" -> 4). The agent in usaspending q5 caught it ("'sub-million' became
1,000,000") and ignored the file. Fixed in `dabcheck/extract/numbers.py` after the run (commit `ce96c0f`); the
November 5 docetl results were produced with the defective parser.

**How agents used it (22 questions)**: 6 right versus 7 and 7.
- DEPS q2 right: the agent cross-checked its own regex against the file ("results do not depend on the DocETL file");
  the fdj run got DEPS q2 right with no DocETL outputs, so the fix is not attributable. DEPS q1 stayed wrong on a
  definition choice (packages whose names contain `>`), with star counts matching the file.
- cve q1-q10: the file covers CVSS only; nine agents said it did not help with the CVE key join, which is what the
  cve questions turn on. cve q8 used it for a score filter and still missed (rows vs distinct CVEs).
- usaspending: agents found the 7% coverage useless ("parsed the same numeric rows I parsed myself"); outcomes
  match the baseline except q2 and q4, which were 1/2 in the baseline.

Takeaway: DocETL's value on DAB depends on extraction being the bottleneck. In the extraction failures of the
review it was a truncated regex (DEPS, now handled by the agents in all three runs) or text that does not contain
the value (usaspending); neither is helped by a better extraction pipeline.

## 5. Text-to-SQL verification (cohort / temporal)

**Reach**: 101 of 104 runs executed single-database SQL; the selection step judged answer-level SQL in 9. The
cohort and temporal failures it targets (crmarenapro q12 date field, civic as-of questions) reached no verifiable
statement except civic q2.

**Verdicts**: all 9 rejected (3 of them wrong in round 1, 6 right). Several rejected statements were Python
templates recovered from the agent's code (`where track_id in {ids}`, `in (%s)`), which the back-translation calls
"truncated" and synthetic execution cannot run; others were rejected for output shape (top-3 rows instead of MAX).

| Question | Round 1 -> round 2 (baseline) | Warning sent | What round 2 did |
|---|---|---|---|
| music q1 | wrong -> **right** (wrong/wrong) | "filters an unspecified list of track_ids (truncated placeholder)" | re-derived the duplicate set, found four records, $1,059.46 |
| music q3 | wrong -> **right** (right/right) | "returns total revenue for every track_id" | re-ran the ranking: "The earlier answer was wrong" |
| civic q2 | wrong -> wrong (wrong/wrong) | "as-of rule missing" (correct diagnosis) | kept the answer: "the verifier's warnings are about the reconstructed SQL" |
| GITHUB q4, agnews q4, imdb q9, music q2, stockmarket q1, yelp q1 | right -> right | output shape / templates | kept the answer, explained why the warnings do not change it |

Takeaway: the measured +2 is consistent with a generic "re-check your answer" second round; the only correct
cohort diagnosis (civic q2's missing as-of rule) did not change the answer. A control condition that sends the
same second-round prompt without verifier content would separate the two.

## 6. Relation to the gap

The results support the gap stated for the project: FDJ and DocETL are configured before the run and their outputs
are optional inputs the agent can (and did) disregard; the SQL verifier judges a finished statement and almost never
sees one in a multi-step DAB run. None observed the steps where the failures happen (a join that loses rows, a parse
that invents values, an as-of rule that is skipped) while the agent was still working. The one useful signal came
from asking the agent to look again.

## 7. Limits

- One trial per condition; baseline two trials. Per-question changes need the noise table in section 2.
- Haiku is the agent and every method LLM; FDJ in particular is designed around a stronger generation model.
- Deviations from the papers are listed in `docs/EXPERIMENTS.md` (blocked FDJ evaluation, refinement cap, SQL
  selection step, one database per verification).
- Code: docetl ran at commit `3a92a66`, sqlverify and fdj at `c74b2cf`-`b9a3fa9` (the differences between these
  commits do not touch the code paths each condition used); the parser fix `ce96c0f` came after all runs.

## 8. Next experiments worth running

1. A "second look" control for sqlverify (same round-2 prompt, no verifier content) on the same 104 questions.
2. A step-level check that runs while the agent works: join row counts and key-rule swings (`audit_join`), parse
   coverage, and as-of / date-field checks on the agent's intermediate tables, reported back before the final answer.
3. A second trial of each condition, or the targeted subset (both-runs-wrong questions) with 3-5 trials.
4. FDJ on cve with a stronger generation model and a larger labelling budget, to separate the method from Haiku.
