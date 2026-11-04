# Live evaluation with claude-haiku-5-5

*Written for the CSE 584 project team.* Script: `experiments/live_haiku_eval.py` (all stages use
`claude-haiku-5-5` for generation, critique, extraction and labelling; replies are cached under
`~/.cache/dabcheck`). Raw output: `experiments/results/live_haiku_eval.json` / `.md`.

## 1. SQL verifiers on known right / wrong query pairs

Three questions where the failure review names the mechanism, each with a correct query and the
query the agents actually wrote. Methods: RT = round-trip critique (threshold 4/5), SE = synthetic
execution (2 answer-first test databases), SC = direct critique, cohort = intent cards.

| case | kind | RT | SE | SC | cohort | AND | OR |
|---|---|---|---|---|---|---|---|
| crmarenapro q12: April anchored on signed date (right) vs created date (wrong) | right | R | R | R | R | R | R |
| | wrong | A | R | A | R | R | A |
| civic q4-style window: `<= 2022-06-01` (right) vs `< 2022-06-01` (wrong) | right | A | A | A | A | A | A |
| | wrong | R | R | R | R | R | R |
| imdb keyword join: integer ids (right) vs digit strings with leading zeros (wrong) | right | A | A | A | A | A | A |
| | wrong | R | R | R | A | R | A |

| method | false accepts | false rejects |
|---|---|---|
| RT | 1/3 | 1/3 |
| SE | 0/3 | 1/3 |
| SC | 1/3 | 1/3 |
| cohort | 1/3 | 1/3 |
| AND of all four | 0/3 | 1/3 |
| OR of all four | 2/3 | 1/3 |

Observations.
- The window-boundary and the leading-zero errors are caught by every LLM-backed verifier; SC's
  reason for the imdb case names the mechanism exactly ("does not strip leading zeros ... keywords
  with zero-padded IDs will be silently dropped"). The cohort cards accept the wrong imdb join
  because a join-key encoding is not a cohort/temporal property; that check is not designed for it.
- crmarenapro q12 is the interesting one: with Haiku as the critic, RT and SC *accept the wrong
  query and reject the right one*. The back-translation of the wrong query ("opportunities created
  between April 1 and April 30, 2023 ...") reads as a faithful restatement of "in April 2023", i.e.
  the verifier shares the agents' reading of the question. SE rejects both queries: one of its two
  synthetic cases encodes the created-date reading and the other the signed-date reading, so neither
  query satisfies both. This is the paper's point that verification cannot resolve a genuinely
  ambiguous question (its Sec. 8), and it reproduces the review's finding that all four agent runs
  chose the created-date reading.
- AND-combination has no false accept here, at the price of the ambiguous case being rejected either
  way (coverage loss), which matches the paper's trade-off (AND: lowest FAR, highest FRR).
- Cost: 72 verifier calls for the six query checks, about $0.015.

## 2. Extraction fallback (DocETL-style map with evidence validation and one gleaning round)

| column | rows sent to Haiku | outcome |
|---|---|---|
| usaspending `amount_text`, rows the code could not parse (vague magnitude prose such as "five-figure", "low-to-mid millions") | 60 | 0 rows received a value: Haiku returned null or its evidence failed the verbatim/number check, so no fabricated amounts entered the column |
| DEPS `Project_Information`, rows missed by the naive `(\d+) forks` pattern | 60 | 60/60 LLM values equal the code extraction with the full pattern set (thousands separators, "forks count of N", "forked N times") |

The evidence check matters: the LLM must quote a substring that contains the number it returns;
on the prose rows it could not, and the pipeline kept those rows as unparsed instead of accepting a
guess. Cost of this stage about $0.01.

## 3. DocETL optimizer on the DEPS extraction map

`optimize_map` over five sample rows of `project_info` with the prompt "Extract the GitHub project
name, its star count and its fork count". The validation agent wrote three criteria (exact
owner/name, counts attached to the project and not confused with open issues, no fabrication when a
count is missing) and judged the original single-prompt map satisfactory (`needs_improvement:
false`), so no rewrite was generated. The five outputs are correct (e.g. ljharb/qs 8073 stars / 746
forks). That is the opportunistic behaviour of Sec. 4.1: decomposition is only attempted when the
validator finds the outputs lacking; for short, single-fact rows it does not.

## 4. FDJ on the cve KEV x vulns join with Haiku

Setup: 400 KEV `cve_ref` keys x 1,000 vulns `cve_id` keys (94 true pairs, from the oracle built on
DAB's corruption code), Haiku as reasoning model (walkthrough, feature descriptions, extractor code,
distance choice), extraction model and labeller; T = 0.9, delta = 0.1; 1,500 uniform pairs labelled,
positives topped up from the oracle; refinement capped at 20,000 candidates. Wall time 55 min, cost
about $2.05 (6,500 calls, most of them per-record feature extraction).

| item | value |
|---|---|
| Haiku labels vs oracle | 1,516 / 1,594 agree (95%); the disagreements are concentrated on true pairs, i.e. Haiku cannot decode most key families either |
| features generated (3 rounds) | `cve_year_sequence_pair` (code, digit edit), `confusable_digit_sequence` (code, OCR look-alikes), `normalized_cve_year` (LLM year extraction), `bare_sequence_candidate` (code, longest digit run), plus the seed `raw_similarity` |
| cost to cover after each round | 80 = every negative, unchanged: no generated feature ranked any positive above the negatives |
| decomposition | `(raw_similarity <= 1)`, i.e. TRUE; T' = 1.0, sample recall 1.0, `target_feasible` = True |
| candidates | 400,000 of 400,000 pairs (candidate recall 1.0, precision 0.0002); refinement skipped by the cap |

Reading. The recall guarantee held trivially: when no feature separates the pairs, Alg. 4 keeps the
scaffold TRUE and FDJ degenerates into the all-pairs join, which is exactly what the paper's cost
model predicts (Sec. 8.2: savings depend on whether features that indicate the join exist and are
found). The generation loop with Haiku proposed only the "plain" families (CVE pattern with
separators, OCR substitutions, year, bare digit run); the DAB keys use 32 families including offsets,
base-36, hex, interleaving and reordering plus an inserted noise fragment, and the offline experiment
had already shown that such plain decoders link under 1% of the keys. The paper used O3 for feature
generation and GPT-4.1 for extraction; a stronger reasoning model (`DABCHECK_MODEL=claude-sonnet-5-5`
or Opus) is the first thing to try, with the labelled examples the cost-to-cover loop already
selects (the hardest positives) as the demonstration set. On the imdb-style identifier problems,
where the decoders are simple, `audit_join` already closes the gap without any LLM (Sec. 1 of
`docs/dabcheck.md`'s results).

## 5. What the three methods buy, and what they do not (summary for the proposal)

No end-to-end accuracy gain has been measured yet: that needs the agent re-runs of conditions B/C/D
in `docs/PROPOSAL.md`. Per mechanism, on the real DAB data:

| mechanism | evidence | expected effect on the 104 questions |
|---|---|---|
| identifier joins | imdb: integer-id rule links 21,046 movies vs 2,371 with the digit-string rule, and `audit_join` warns without an LLM; cve: FDJ keeps precision 1 and recall >= 0.9 with oracle labels, but Haiku-generated features bring no cost reduction | imdb-type errors (zero padding, `#`, OCR) are fixable by the audit; cve-type decoding is not fixed by Haiku-driven FDJ |
| extraction | DEPS q2: coverage 67% -> 100%, all five ground-truth fork counts exact, Haiku fallback 60/60 correct; usaspending: the coverage warning reports that 94% of amounts are vague prose and the fallback fabricates nothing | DEPS q1/q2 become answerable; usaspending q1/2/5/8/9 remain unanswerable exactly (the data, not the extractor) |
| cohort / temporal | window boundary and leading-zero join: 0 false accepts across RT/SE/SC; crmarenapro q12: Haiku critics share the agents' reading, SE rejects both readings | catches the mechanical variants; genuinely ambiguous questions (q12, PANCANCER q3, stockmarket q4) turn into abstentions at best |

Upper bound from the review's both-runs-wrong table: identifier + extraction questions are 14/36
(terra) and 11/32 (Haiku), cohort + temporal 15/36 and 8/32. Fixing every identifier and extraction
question would add at most about 10 points for Haiku and 13 for terra; the cohort/temporal share is
mostly interpretation, which verification converts into abstention rather than correct answers.
