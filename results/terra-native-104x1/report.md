# Terra DataAgentBench — complete 104-task evaluation

One independent trial per original question, descriptions+hints. Original query-specific validators. Pass@5 is not available. Authors native Codex driver was unavailable; this is a documented Codex CLI reconstruction. Offline/connection tests are excluded. Infrastructure failures are separate from wrong answers.

**Correct: 59/104 scored; unscored: 0; coverage: 104/104.**

Dataset-macro Pass@1: 62.59%. Question-weighted accuracy: 56.73%. Pass@5: unavailable.

Recorded input tokens: 34,994,764; cached input: 14,814,739; output: 558,239; tool calls: 1,226. Dollar cost: unavailable. Excluded attempts are accounted for separately in attempt-accounting.json.

| Dataset | Scored | Correct | Accuracy | Unscored |
|---|---:|---:|---:|---:|
| DEPS_DEV_V1 | 2 | 1 | 50.00% | 0 |
| GITHUB_REPOS | 4 | 3 | 75.00% | 0 |
| PANCANCER_ATLAS | 3 | 1 | 33.33% | 0 |
| PATENTS | 3 | 2 | 66.67% | 0 |
| agnews | 4 | 1 | 25.00% | 0 |
| bookreview | 3 | 3 | 100.00% | 0 |
| civic_unstructured | 10 | 3 | 30.00% | 0 |
| crmarenapro | 13 | 10 | 76.92% | 0 |
| cve | 10 | 2 | 20.00% | 0 |
| googlelocal | 4 | 4 | 100.00% | 0 |
| imdb | 10 | 7 | 70.00% | 0 |
| krama | 10 | 4 | 40.00% | 0 |
| music_brainz_20k | 3 | 3 | 100.00% | 0 |
| stockindex | 3 | 3 | 100.00% | 0 |
| stockmarket | 5 | 4 | 80.00% | 0 |
| usaspending | 10 | 4 | 40.00% | 0 |
| yelp | 7 | 4 | 57.14% | 0 |

## Failure review

10 failed questions have selected trace-based reviews. This is not an exhaustive semantic adjudication. Official grades are unchanged. See failure_analysis.csv and review-notes.json for evidence.

**PANCANCER_ATLAS/query1 — grouping_field_mismatch:** Valid run trace item_9 groups by histological_type and returns Astrocytoma/Oligoastrocytoma/Oligodendroglioma. The unchanged validator expects five ICD-O-3 histology codes. The answer omits the required codes and merges distinct expected groups.

**DEPS_DEV_V1/query1 — incomplete_text_number_extraction:** Trace item_7 extracts only ([0-9]+) stars from project text. Read-only data verification finds TypeScript described as stars count of 94931, lodash as stars count of 57779, and Svelte as 73,499 stars. The regex excludes the first wording and truncates comma-formatted counts, yielding the wrong ranking. Original validator correctly rejects the missing above-cutoff packages.

**PANCANCER_ATLAS/query3 — cohort_filter_mismatch:** Valid trace item_8 computes the official 305.1239198 for all clinical patients (N=1059), but final answer selects the PASS-coverage cohort (N=762) and reports 325.34. It restricts the non-mutated denominator to patients with at least one PASS mutation entry; the official expected cohort does not.

**PATENTS/query3 — entity_extraction_and_code_granularity:** Valid session patch for investigate.py uses only the phrase publication number to extract identifiers; it finds 55 UC entries although item_5 reports 169 descriptions mentioning UNIV CALIFORNIA. This restricts the citation join. The final answer also supplies detailed codes G01V1/01 and H01L21/0262 although the question requests CPC subclasses. Official grader reports missing BLOOM ENERGY CORP and its expected subclass title.

**GITHUB_REPOS/query1 — numeric_mismatch_unresolved:** Trace item_13 computes 17/115 when including lowercase readme.md; final answer narrows to 16/111 exact-case README.md and reports 14.4%. Original grader requires a numeric value rounding to 0.33. Independent read-only probes reproduced the trace counts but did not establish the official denominator. Do not claim a verified semantic root cause for this case.

**agnews/query2 — semantic_classification_mismatch:** Valid run reads the article texts and reports 18 Science/Technology articles among 111 by Amy Jones. Official fraction is 0.144144... (=16/111). The denominator agrees; the classified numerator differs. Exact two misclassified documents were not independently adjudicated.

**agnews/query3 — heuristic_topic_classification:** Valid trace item_13 uses topical regular-expression cues over article texts after metadata filtering. It reports 337.73 per year; the original grader expects 336.63636 within 0.01. The topic-selection heuristic does not reproduce the required count.

**agnews/query4 — heuristic_topic_classification:** Valid trace items_11 and_12 build keyword/naive-Bayes-like topic classifications; the leading region changes across smoothing settings. Final answer chooses South America; original validator expects Africa.

**cve/query5 — range_endpoints_vs_version_values:** Valid trace item_16 shows version_text is * and separate start/end bounds for three ranges. The final answer excludes * and counts six boundary strings as distinct affected versions. Original grader expects 1. This changes the counted field from stored version values to range endpoints.

**imdb/query5 — row_selection_instead_of_independent_minima:** Original query.json asks for the alphabetically first company name, first rating value and first title among qualifying movies. Valid trace item_11 loops through sorted companies and breaks at the first matching company, then chooses a rating/title within that company. Final answer returns one matching record (O Films / 6.5 / Parking Ticket), rather than independently minimizing each requested column over the full qualifying set. Official grader requires rating 1.0.
