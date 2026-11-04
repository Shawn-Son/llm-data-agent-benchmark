# Failure review — full trajectory analysis (terra × 2, Haiku × 2)

**Scope.** Every question that any of the four analysed runs got wrong: **61 questions, 166 wrong runs** (terra original + run 1: 87; Haiku runs 1–2: 79). Each wrong run was read step by step: every command, output and agent-written script, against the unchanged validator and the ground truth. Each wrong run got one primary category, sub-issues, and the first divergence step with a verbatim excerpt. Where the same model was right in one run and wrong in the other, the reviewer also recorded what the right run did differently.

**Evidence.** terra 42 supported / 35 likely / 10 unresolved; Haiku 56 / 17 / 6. The earlier summary review, built from the grader reason and final answer only, had 27 and 20 unresolved.

**Limits.** This is a retrospective assistant review (six parallel reviewers using shared instructions), not an independent judge. Databases were not re-queried. Haiku's hidden thinking is not recorded, so its causes are judged from its actions.

Per-question findings: `[A–F]_*.json` (schema in `REVIEW_INSTRUCTIONS.md`). Process signals per run: `signals.json`.

## 1. terra — what goes wrong most

| # | Problem | Scale | Detail from the traces |
|---|---|---|---|
| 1 | Confident answers without a cross-check | `no_verification` in 50/87 wrong runs; 0 hedged | agnews q3 reports 337.73 business articles/year, a number no command produced. civic q6 run 1's final 76,886,000 comes from no visible computation (X3). |
| 2 | Finds the right value, then abandons it | 6 questions | cve q9 prints 8, then loosens the matcher. cve q10 prints "products 5", then answers 14. crmarenapro q12 computes the expected agent NDEBIA4 (step 6), then returns the created-date one. krama q3 computes the expected 12,964.87 (step 17), then adds Puerto Rico. yelp q2 prints PA 3.70, then uses the metadata count. crmarenapro q13 run 0 has the right ranking at step 5, then switches. |
| 3 | Cohort / filter definition (C1) | 11 questions | imdb q6 uses a case-insensitive `LIKE '%An%'`. GITHUB q4 keeps torvalds/linux, which has no language row. PANCANCER q3 restricts to mutation-profiled patients (χ² 325 vs 305). |
| 4 | Keyword-heuristic labels (S1) | 9 questions | agnews topic labels. civic "Construction" vs "Design". crmarenapro stage labels. |
| 5 | Time logic | static status T1: 5 questions (terra only); date windows/formats T2: 5 | civic q4/q6/q10: hand-written project lists ignore the "latest report on or before the grant" rule (0.66, $123M, 0.39). krama q10 uses whole calendar days instead of the storm epoch span (0.000708 vs 0.000748). yelp q3/q7: string-prefix filters drop 2 of 3 date formats. |
| 6 | Hand-typed lists / IDs | `hardcoded` in 23/87 wrong runs | civic project lists; cve candidate lists. |

## 2. Haiku — what goes wrong most

| # | Problem | Scale | Detail from the traces |
|---|---|---|---|
| 1 | Noisy identifier handling (J1, J5) | 10 questions | cve key decoding. imdb q6/q9/q10 compare IDs as digit strings with leading zeros kept, so only 119 of 937 movies link in q10; the runs that cast to bigint were right. |
| 2 | Gives up or hedges (X1) | `hedged` in 27/79 wrong runs, `declined` 3 | usaspending q1/q5/q9 count only the 522 numeric rows of 10,266 and declare a lower bound (q1: 71 vs 898). cve q3/q4/q8 decline to give a number. |
| 3 | Answer presentation vs validator (V1) | 7 questions, 10 runs | cve q5 "**Answer: 1.**" is correct but the regex rejects "1." followed by a period. civic q7/q3 give the correct empty answer but name candidates. PATENTS q3 (validator bug). googlelocal q2/q3 (gmap_id column between name and score; weekday-only hours). usaspending q4 (a trailing bold "**Method**" heading is taken as the answer). |
| 4 | Regex / prose parsing gaps (E2, E1) | 8 and 5 questions | DEPS q2 `(\d+) forks` turns 30,522 into 522. krama q6 matches the substring "violation recorded", which also matches "no violation recorded" (22 vs 4). music_brainz q1 title `LIKE '%get me bodied%'` misses "GetMe Bodied". |
| 5 | Entity merging (J2) | 7 questions | civic q10: Annual Street Maintenance 2021/2022 split gives 0.56, merged gives 0.69 (expected). music_brainz duplicate tracks. |
| — | Harness signals | `tmp_loss` 53/79, `timeout` 33/79 | Frequent, but reviewers found no answer they changed on their own; they cost turns. |

## 3. Common to both models

1. **Noisy identifier decoding** (terra 9 q, Haiku 10 q; 27 wrong cve runs). Loose digit-subsequence rules over-match (cve q8 = 244 in both terra runs vs 58); strict rules miss whole encoding families.
2. **Text-to-value extraction** (E1 + E2). In usaspending about 9,744 of 10,266 `amount_text` rows are vague prose ("five-figure", "low-to-mid millions"), while the hint says formats are exact. terra classifies with keyword regexes (900 vs 898); Haiku declares floors (71).
3. **Entity normalization** (J2, 7 q each). civic "Annual Street Maintenance" and the guardrail projects; usaspending q6, where all four runs give 57 vs 56.
4. **Cohort and filter definitions** (C1: terra 11 q, Haiku 6 q).
5. **Shared wrong answers.** 21 questions are wrong in all four runs. The two models give the same wrong answer in imdb q9 (101188), crmarenapro q12 (NJgAIAW), usaspending q6 (57), PANCANCER q1 (histology names) and stockmarket q4 (up-day ranking).

## 4. Category detail (questions with the sub-issue: terra / Haiku)

| Category | Detailed issues | Trace evidence | When the warning fires | What to do |
|---|---|---|---|---|
| Identifier joins and identity | J1 noisy keys 9/10; J2 entity merge 7/7; J5 wrong link source 3/2; J4 positional alignment 2/0 | cve q8 244; imdb string IDs; civic merges; krama q7 T0 `zip(ages, values)` | Match counts swing with the rule; leading zeros; many unmatched rows | Canonical keys (cast / strip); recall against the clean side; cardinality checks |
| Extraction and representation | E2 regex gaps 7/8; E1 prose numbers 6/5; E3 representation 3/1; E4 manual transcription 2/0; E5 noisy fields 2/0 | DEPS forks 522; PANCANCER names vs ICD-O-3; cve q5 range bounds as versions; imdb q6 shortened copied IDs | Low parse coverage; answer unit differs from the question | Report parse coverage; keep raw + parsed; check the required representation |
| Cohort and aggregation | C1 filters 11/6; C2 wrong source 3/1; C3 ranking 2/2; C4 denominator 1/1; C5 first match 1/1 | yelp q2 metadata count; stockmarket q4 ranking; imdb q5 first row instead of per-column minima | Population or denominator changes between steps | Record cohort lineage and each aggregate's denominator |
| Temporal state and status | T1 static status 5/0; T2 parsing / windows 5/1; T3 misdated document 2/2; T4 wrong date field 1/2 | civic rid_0010 stamped Oct 2021 but its text says Jan 2022; crmarenapro q12 CreatedDate vs CompanySignedDate (all four runs); krama q10 window | No dated join; conflicting stated vs internal dates | As-of joins; reconcile stated and internal dates |
| Semantic classification | S1 keywords 9/5; S2 policy judgment 3/3; S3 category scope 3/1; S4 manual labels 1/1 | agnews labels are not in the database; googlelocal "massage"; crmarenapro q7 365-day validity window missed by all four runs | Labels come from keywords; an audited sample disagrees | Audit a labelled sample; prefer category fields; check every policy clause |
| Execution and unsupported result | X1 gave up / estimate 6/6; X3 answer not backed by computation 2/0; X2 tool failure 1/0 | Haiku lower bounds; terra uncomputed values; krama q2 T0 parser fails, then answers "Wyoming" | The final value appears in no output; the answer says "estimate" | Require the final value to be traceable to a printed output |
| Answer format vs validator | V1 1/7; V3 rounding 1/0 | cve q5 "1."; krama q9 T0 2.4432 vs 2.4431 | — | Put the final value alone on its own line |

## 5. Validator and task issues (official grades unchanged)

- **False negatives (answer right, rejected): 11 runs, 10 Haiku + 1 terra.**
  - cve q5 ×2
  - civic q7 ×2, civic q3 H2
  - PATENTS q3 ×2: `find()` searches a no-space name in space-preserving text
  - googlelocal q3 T1/H1/H2: the validator requires the full 7-day schedule
  - usaspending q4 H1: the last bold span is taken as the answer
- **False positives (wrong, but passed): 9 runs, all Haiku.** Lenient "value appears anywhere in the text" checks reward long, multi-candidate answers.
  - cve q9 H1: declined, but an unrelated "8" matched
  - krama q7 H1/H2: an age "60" appears in the listed ages
  - krama q2 H2: answers California, but "Idaho" is mentioned
  - krama q10 H2: the expected value is mentioned as an alternative
  - crmarenapro q7 H2: the expected ID is named while being ruled out
  - agnews q4 H1: contains the substring "Africa"
  - civic q9 H1: a table row names the expected funding source
  - usaspending q8 H1: 25 is mentioned as an alternative
- **Net effect.** For Haiku the two roughly cancel (10 vs 9); for terra it is 1 vs 0.
- **Task or ground-truth ambiguity.**
  - usaspending hints vs data: vague prose amounts (q1/2/5/8/9)
  - GITHUB q1: the ground-truth denominator of 3 cannot be reproduced
  - agnews: needs the original AG News labels, which are not in the database
  - stockmarket q4: ranking metric undefined
  - krama q3: whether Puerto Rico counts
  - PANCANCER q1 (codes vs names) and q3 (denominator)
  - PATENTS q2 wording
  - imdb q9 (1040)
  - usaspending q6 (+1)

## 6. Process signals (runs within the 61 failing-question set)

| | terra wrong (87) | terra right (34) | Haiku wrong (79) | Haiku right (43) |
|---|---:|---:|---:|---:|
| hedged / declined answer language | 1 / 0 | 0 / 0 | 29 / 8 | 13 / 1 |
| /tmp file lost | 4 | 2 | 54 | 28 |
| 2-minute timeout | 0 | 0 | 33 | 13 |
| failing-command rate | 10.4% | 11.0% | 11.6% | 11.9% |
| median duration (s) | 130 | 93 | 172 | 158 |

The hedged and declined counts in this table come from a regex over answers. The reviewer-coded counts in the tables above are similar: Haiku 27 hedged, 3 declined.
