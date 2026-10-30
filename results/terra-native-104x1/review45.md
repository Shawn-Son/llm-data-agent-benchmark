# DataAgentBench: gpt-5.6-terra results and all-failure review

## 1. Performance and scope

104 original questions across 17 datasets, one independent trial each, original descriptions + hints, unchanged validators. **59 correct, 45 wrong, 0 unscored. Micro accuracy: 56.73%; equal-dataset macro Pass@1: 62.59%. Pass@5 was not measured.**

The reconstructed Codex CLI harness differs from the authors' exact driver/system prompt/timeouts, so this is not a controlled ranking against their models. Earlier infrastructure failures were corrected and excluded by the documented rule; the final sweep completed. Internal failed commands can still occur within scored trials.

| Model | Correct / total | Micro accuracy | Macro Pass@1 | Tool calls |
| --- | --- | --- | --- | --- |
| gpt-5.6-terra | 59 / 104 | 56.73% | 62.59% | 1,226 |

Recorded usage: 34,994,764 input tokens (14,814,739 cached) and 558,239 output tokens. Actual dollar billing was not verified.

## 2. Dataset detail

| Dataset | Correct / total | Accuracy |
| --- | --- | --- |
| DEPS_DEV_V1 | 1/2 | 50.0% |
| GITHUB_REPOS | 3/4 | 75.0% |
| PANCANCER_ATLAS | 1/3 | 33.3% |
| PATENTS | 2/3 | 66.7% |
| agnews | 1/4 | 25.0% |
| bookreview | 3/3 | 100.0% |
| civic_unstructured | 3/10 | 30.0% |
| crmarenapro | 10/13 | 76.9% |
| cve | 2/10 | 20.0% |
| googlelocal | 4/4 | 100.0% |
| imdb | 7/10 | 70.0% |
| krama | 4/10 | 40.0% |
| music_brainz_20k | 3/3 | 100.0% |
| stockindex | 3/3 | 100.0% |
| stockmarket | 4/5 | 80.0% |
| usaspending | 4/10 | 40.0% |
| yelp | 4/7 | 57.1% |

CVE, civic_unstructured, krama and usaspending account for **27/45 failures (60%)**. Four datasets are perfect in this single small run; this does not establish general reliability.

## 3. What went wrong, and what to catch during execution

All 45 failed traces were reviewed (35 added to the earlier 10). **16 have a directly visible mechanism or discrepancy; 29 remain unresolved at the exact-cause/row level.** This is a retrospective assistant review, not a second independent judge. Each failure receives one primary review category. Shares below describe review categories, including hypotheses; they are not proven causal rates or repair rates.

| Primary review category | Runs | Share of 45 |
| --- | --- | --- |
| Extraction and representation | 10 | 22.2% |
| Identifier joins and identity | 10 | 22.2% |
| Cohort and aggregation | 9 | 20.0% |
| Temporal state and status | 9 | 20.0% |
| Semantic classification | 5 | 11.1% |
| Execution and unsupported result | 1 | 2.2% |
| Final-answer rounding | 1 | 2.2% |

| Category / real example | When to warn | What to do | Can we fix it? |
| --- | --- | --- | --- |
| Extraction and representation: DEPS q1: star regex misses label-first/comma-formatted counts; imdb q6 copies shortened IDs. | Low parse coverage; IDs change after copying output. | Keep raw + parsed values; use machine-readable joins. | Potentially; not tested. |
| Identifier joins and identity: CVE q6: similarity thresholds change candidate matches sharply; krama q7 aligns patients by position. | Unmatched/duplicate keys or unstable match counts. | Canonical keys, cardinality checks, patient-ID joins. | Partly; identity may need adjudication. |
| Cohort and aggregation: PANCANCER q3: N=1059 gives 305.12, then N=762 gives final 325.34. Yelp q2 mixes metadata counts with review rows. | Population changes; ranking and average use different sources. | Record cohort lineage and each aggregate denominator. | Potentially; semantics still matter. |
| Temporal state and status: Civic q6 applies a static disaster blacklist despite an as-of-grant requirement; 123.003M versus 88.615M. | Time-dependent eligibility has no dated join. | Use latest report at or before each grant. | Partly; report interpretation needed. |
| Semantic classification: agnews q2 labels 18/111 as Science/Technology; validator implies 16/111. | Labels change across rules or disagree on an audited sample. | Review disputed labels and policy clauses. | Uncertain; exact disputed rows unresolved. |
| Execution and unsupported result: krama q2: geometry parser fails; final Wyoming lacks a successful intersection (expected Idaho). | Calculation fails but a confident result follows. | Require a successful geometry computation. | Potentially; repair not tested. |
| Final-answer rounding: krama q9: tool 2.4431451613 should round to 2.4431; final says 2.4432. | Final number differs from the cited tool value at requested precision. | Format directly from the computed scalar. | Deterministic example; no agent replay. |

The most concrete opportunity is preserving computed results and their population: krama q9 has a rounding error; PANCANCER q3 and krama q3 contain validator-matching intermediate calculations before a different cohort is selected. An intermediate number matching the key alone is not proof of a valid algorithm (notably CVE q9/q10).

**Possible task/validator ambiguities:** imdb q9 asks for an alphabetically first vote count; the trace returns 101188 while the validator requires 1040. Stockmarket q4 has an unresolved ranking interpretation; crmarenapro q12 differs between created-month and signed-month cohorts. Keep official grades unchanged pending adjudication. The screenshot's 352 failures, model scores and LIMIT examples describe another experiment and are not reused here.

## 4. Improvement: what is measured and what is not

No runtime-warning or repair intervention was tested. There is no measured repair rate, fixable-failure total or supported upper-bound accuracy estimate. Each additional corrected question would add 1/104 = 0.96 percentage points to micro accuracy. If a future intervention fixes 1, 5 or 10 failures with no regressions, accuracy would be 57.69%, 61.54% or 66.35%, respectively. These are arithmetic scenarios, not forecasts.

Next experiment: compare an unchanged rerun control against warnings for (1) final-value consistency, (2) cohort/denominator changes and (3) join/parse coverage. Hold model and budget fixed; measure net corrections, regressions, false warnings, extra tokens and latency with unchanged validators. Resolve ambiguous tasks separately, without tuning detectors to known answer values.

## 5. Evidence and completion record

Slurm sweep 65052253 and archive job 65056532 completed. Original source commit: `61fb21e0766d775acae443f6074f5d498e95f938`. Full retained trajectories and validators are on Great Lakes. The original 484,033,085-byte archive has SHA-256 `4c2135f695e9ca03bd1d35e109465bbb1ba91ba5fea435aac9834b219abb8b00`; this later review is a separate supplement and does not change that archive or its grades.

[Per-question results](https://github.com/Shawn-Son/llm-data-agent-benchmark/blob/main/results/terra-native-104x1/runs.csv) · [Original archive record](https://github.com/Shawn-Son/llm-data-agent-benchmark/blob/main/results/terra-native-104x1/ARCHIVE.json) · [Structured 45-case review](https://github.com/Shawn-Son/llm-data-agent-benchmark/blob/main/results/terra-native-104x1/review45.json) · [Review generator](https://github.com/Shawn-Son/llm-data-agent-benchmark/blob/main/results/terra-native-104x1/build_review45.py)

## Appendix: all 45 failed runs

Retrospective assistant review of original questions, unchanged validators, final answers and retained command traces. One primary review category per failed run; no independent second judge or repair experiment. Compact extraction limits each command output to 1400 characters, so unresolved causes are explicitly retained. Supported means the mechanism or discrepancy is directly visible, not that a repair was replayed or all causal rows proved.

### DEPS_DEV_V1 q1 — Extraction and representation

**Evidence status:** Supported. **Repair tested:** No.

Star parsing requires digits immediately before 'stars'; it misses 'stars count of 94931' and mishandles formatted counts. The resulting top packages omit an above-cutoff package required by the validator.

**Check/action:** Check parse coverage and retain raw text beside parsed stars; parse comma-separated and label-first forms before ranking.

**Official validator:** Missing or mis-versioned above-cutoff package: @dmrvos/infrajs>0.0.6>typescript 2.6.2

**Trace:** `runs/DEPS_DEV_V1/query1/commands.json`; `item_4`, `item_5`, `item_6`, `item_7`. Validator SHA-256: `691a1910f0eb76e20b7d0652141584320b5bcfcaa399f07d8601f0dbc00c2d35`.

### GITHUB_REPOS q1 — Cohort and aggregation

**Evidence status:** Unresolved. **Repair tested:** No.

Final 16/111 (14.4%) differs from validator 0.33; another normalization gives 17/115. The trace does not establish the benchmark's intended denominator or the exact missing repositories.

**Check/action:** Reconcile row-level numerator and denominator under the original task's repository and language definitions.

**Official validator:** No value in LLM output rounds to 0.33

**Trace:** `runs/GITHUB_REPOS/query1/commands.json`; `item_7`, `item_11`, `item_12`, `item_13`. Validator SHA-256: `c8e979be70776b67ee32372ac1e77b75f7474946809dc81d4941821bf5683bd5`.

### PANCANCER_ATLAS q1 — Extraction and representation

**Evidence status:** Supported. **Repair tested:** No.

The answer lists histological_type names, while the validator requires five ICD-O-3 codes, including 9382/3. The queried representation and required answer representation differ.

**Check/action:** Check requested histology vocabulary against the schema and map names to the requested codes with provenance.

**Official validator:** Missing histology type: 9382/3

**Trace:** `runs/PANCANCER_ATLAS/query1/commands.json`; `item_5`, `item_6`, `item_7`, `item_8`, `item_9`. Validator SHA-256: `3f1b15e3c24c1ce258ba064fcc3f2523ee4b7c8079ab58c5ac215cd90d1d6d7a`.

### PANCANCER_ATLAS q3 — Cohort and aggregation

**Evidence status:** Supported. **Repair tested:** No.

The full clinical cohort (N=1059) gives chi-square 305.1239198, matching the validator. The final answer instead uses the PASS-coverage subset (N=762), giving 325.34.

**Check/action:** Warn when a later join changes the analysis cohort; preserve counts and justify each added restriction.

**Official validator:** No value in LLM output matches 305.12, 305.1, or 305

**Trace:** `runs/PANCANCER_ATLAS/query3/commands.json`; `item_5`, `item_7`, `item_8`, `item_9`. Validator SHA-256: `14b8be8849e25f4ba71b0347589ade0e51dec3e8a51f1273b485244981427520`.

### PATENTS q3 — Extraction and representation

**Evidence status:** Supported. **Repair tested:** No.

The publication-number-only regex finds 55 UC records versus 169 relevant descriptions, losing join coverage. The answer also uses detailed CPC codes rather than subclass titles and omits BLOOM ENERGY CORP.

**Check/action:** Audit unmatched publication identifiers and CPC hierarchy; compare parse coverage across text forms before aggregation.

**Official validator:** No match for: BLOOM ENERGY CORP + PROCESSES OR MEANS, e.g. BATTERIES, FOR THE DIRECT CONVERSION OF CHEMICAL ENERGY INTO ELECTRICAL ENERGY

**Trace:** `runs/PATENTS/query3/commands.json`; `item_4`, `item_5`, `item_7`, `item_8`. Validator SHA-256: `c34efa6c273789795d3bf52a02e11503924644a665fa81ca752914a0c5577d50`.

### agnews q2 — Semantic classification

**Evidence status:** Unresolved. **Repair tested:** No.

The agent labels 18 of Amy Jones's 111 articles Science/Technology; the validator implies 16/111. The exact two disputed labels have not been independently adjudicated.

**Check/action:** Compare article-level labels against an independently reviewed sample; do not infer the two incorrect rows from the aggregate alone.

**Official validator:** Ground truth '0.14414414414414414' (tol=0.0001) not found in LLM output: Amy Jones authored 111 articles. Of those, 18 are Science/Technology articles.  The fraction is **18/111 = 6/37**, or approximately **16.2%**.

**Trace:** `runs/agnews/query2/commands.json`; `item_5`, `item_6`, `item_7`, `item_8`, `item_9`. Validator SHA-256: `4f38f4768db4b5bc392efdc495fe5d98a20d937bed9a773ae876445dd6287145`.

### agnews q3 — Semantic classification

**Evidence status:** Unresolved. **Repair tested:** No.

Keyword-based topic assignment gives 337.73 business articles/year versus 336.6363636. This trace does not establish an answer-causing LIMIT truncation; topic labels remain the main hypothesis.

**Check/action:** Audit business labels and geographic/year filters on the difference set; measure label precision before changing the count.

**Official validator:** Ground truth numeric value '336.6363636363636' (tol=0.01) not found in LLM output: The average is **337.73 business articles per year** in Europe from 2010 through 2020 (inclusive).

**Trace:** `runs/agnews/query3/commands.json`; `item_7`, `item_8`, `item_9`, `item_10`, `item_11`, `item_13`. Validator SHA-256: `809d8d3f011655336e2579577b93681b2f7170eadccf08551de74190e9a61b7f`.

### agnews q4 — Semantic classification

**Evidence status:** Unresolved. **Repair tested:** No.

Keyword and smoothed classifier variants lead to South America, while the validator expects Africa. The trace shows sensitivity to heuristic classification, not a verified corrected set of World articles.

**Check/action:** Compare category counts across classifiers and manually review records that change the winning continent.

**Official validator:** Ground truth 'Africa' not found in LLM output: South America published the most World-category articles in 2015.

**Trace:** `runs/agnews/query4/commands.json`; `item_8`, `item_9`, `item_10`, `item_11`, `item_12`, `item_14`. Validator SHA-256: `a90e70fefb2f2b97c408d9f236d1b1f07037e5bf553162157c6df36b627a8776`.

### civic_unstructured q10 — Temporal state and status

**Evidence status:** Unresolved. **Repair tested:** No.

Hard-coded completed-project sets and manual temporal adjustments produce 12031000/18143000, reported as 0.66, versus 0.69. Exact grant-to-status reconciliation remains open.

**Check/action:** Build a dated project-status ledger and attach each grant to the latest report available at its date.

**Official validator:** Ground truth '0.69' (tol=0.01) not found in LLM output: 0.66

**Trace:** `runs/civic_unstructured/query10/commands.json`; `item_17`, `item_18`, `item_19`, `item_21`. Validator SHA-256: `91330e6b5237efd23331ff9536981bb448b885f0ec4b08bf4a5c4525f47f2ac6`.

### civic_unstructured q2 — Temporal state and status

**Evidence status:** Unresolved. **Repair tested:** No.

The answer selects Michael Landon HVAC at 15509000; the validator expects Corral Canyon Culvert Repairs at 13460000. Narrative completion statements and report-section status may differ; the precise status interpretation is unresolved.

**Check/action:** Adjudicate dated section headers versus narrative status before ranking completed projects.

**Official validator:** Missing in LLM output: project name 'Corral Canyon Culvert Repairs', amount '13460000'

**Trace:** `runs/civic_unstructured/query2/commands.json`; `item_5`, `item_6`, `item_7`, `item_8`, `item_9`. Validator SHA-256: `236e1a16fb849f52e94459701105cd0ca8632cba5148acf336f8402a4c160e8a`.

### civic_unstructured q3 — Temporal state and status

**Evidence status:** Unresolved. **Repair tested:** No.

Name canonicalization and a manually selected completed set yield Municipal Fund 8/29 and PPP 9/34; the validator expects no qualifying funding source. Status membership and deduplication denominator are not reconciled.

**Check/action:** Publish the unique-project denominator and completed membership per source, then inspect disputed aliases and statuses.

**Official validator:** Ground truth is empty, but output lists funding source(s): ['Public-Private Partnership', 'Municipal Fund']

**Trace:** `runs/civic_unstructured/query3/commands.json`; `item_8`, `item_9`, `item_10`, `item_11`, `item_12`, `item_13`. Validator SHA-256: `a540e9a014276d31a68f44fadec6dcd104d101dab05f4cc338563f5e2aad7e2a`.

### civic_unstructured q4 — Temporal state and status

**Evidence status:** Unresolved. **Repair tested:** No.

Manual report-date handling and token-Jaccard section matching (threshold 0.2) produce 0.31 versus 0.34. A specific causal row has not been isolated.

**Check/action:** Preserve report dates, tied-date documents and match scores; inspect low-confidence project-to-section links.

**Official validator:** Ground truth '0.34' (tol=0.01) not found in LLM output: 0.31

**Trace:** `runs/civic_unstructured/query4/commands.json`; `item_10`, `item_11`, `item_12`, `item_13`, `item_14`, `item_15`, `item_16`. Validator SHA-256: `03badfb8ef33f2426421edb27489c3b3dd34cc202a6360bafa3eac1e0bbdfc69`.

### civic_unstructured q5 — Temporal state and status

**Evidence status:** Unresolved. **Repair tested:** No.

Manual project selection and amount adjustments yield 72061000/17 = 4238882.35 versus 4401352.94. The exact omitted or misclassified grants are not proven.

**Check/action:** Reconcile each project's status transitions and grant amounts in an auditable ledger before averaging.

**Official validator:** Ground truth '4401352.94' (tol=0.1) not found in LLM output: The average total funding received was **$4,238,882.35** per qualifying project.  This is based on 17 projects with status changes and $72,061,000 in combined in-period funding.

**Trace:** `runs/civic_unstructured/query5/commands.json`; `item_10`, `item_11`, `item_12`, `item_13`, `item_14`, `item_15`, `item_16`. Validator SHA-256: `04dcefd2978667fb4039d720e54699c3884babcc6de249ebcbe478d90e3110ba`.

### civic_unstructured q6 — Temporal state and status

**Evidence status:** Supported. **Repair tested:** No.

A static disaster-project prefix blacklist is applied across years, although eligibility is required as of each grant. The answer gives 123003000 versus 88615000, with the same year 2023.

**Check/action:** Require an as-of date on status joins; compute eligibility per grant instead of one global project label.

**Official validator:** Missing in LLM output: amount '88615000'

**Trace:** `runs/civic_unstructured/query6/commands.json`; `item_10`, `item_11`, `item_12`, `item_13`, `item_14`, `item_15`, `item_16`, `item_17`, `item_18`. Validator SHA-256: `f3c8e7b5c984647cdf0a6c122ffab83d40fcba6bc14ce4bf100eedd6b6a5e709`.

### civic_unstructured q9 — Temporal state and status

**Evidence status:** Unresolved. **Repair tested:** No.

Hard-coded aliases/disaster labels and omitted unmatched projects yield PPP 16/31, excluding it from the answer although the validator requires it. Exact membership is not independently reconciled.

**Check/action:** Expose unmatched projects and source denominators; resolve dated disaster status before thresholding.

**Official validator:** Missing funding source(s) in LLM output: ['Public-Private Partnership']

**Trace:** `runs/civic_unstructured/query9/commands.json`; `item_7`, `item_8`, `item_9`, `item_10`, `item_11`. Validator SHA-256: `0a62ed854d0531f492d98e2181b97708305dd5801101dbce8cbda420bbaf8d63`.

### crmarenapro q12 — Temporal state and status

**Evidence status:** Supported. **Repair tested:** No.

The trace compares April-created and April-signed contracts. The former selects 005Wt000003NJgAIAW (49 days), the latter 005Wt000003NDEBIA4 (304 days), which the validator expects. Final selection uses creation month.

**Check/action:** Declare the date field used for the April cohort; the wording's temporal interpretation should be adjudicated, not silently changed.

**Official validator:** Found agent IDs ['005Wt000003NJgAIAW'], but expected '005Wt000003NDEBIA4'

**Trace:** `runs/crmarenapro/query12/commands.json`; `item_5`, `item_6`. Validator SHA-256: `99476c2b08ba7f07bfbe1fb4fd32938a5a78c7942e88fb57c35da748e6c7d2cc`.

### crmarenapro q13 — Cohort and aggregation

**Evidence status:** Supported. **Repair tested:** No.

The calculation restricts both contract-signing and order-effective dates, and allocates orders through account-level opportunity owners. It returns NEa3IAG rather than NIXCIA4. Extra filtering and possible owner fan-out are visible; their separate effects are not isolated.

**Check/action:** Check eligibility dates against the policy and assert order-to-owner join cardinality before revenue aggregation.

**Official validator:** Found agent IDs ['005Wt000003NEa3IAG'], but expected '005Wt000003NIXCIA4'

**Trace:** `runs/crmarenapro/query13/commands.json`; `item_5`, `item_6`, `item_7`. Validator SHA-256: `cf707902d5ccb87233fbba008ebc70d6e7001d2f77e10ddebeb082575ded4486`.

### crmarenapro q7 — Semantic classification

**Evidence status:** Unresolved. **Repair tested:** No.

The relevant scalability article ka0Wt000000EoD3IAK is retrieved, but the final answer is None. Retrieval alone succeeded; whether the response breaches the article requires a clause-by-clause case review.

**Check/action:** Link each policy obligation to case evidence and record unmet obligations before concluding no violation.

**Official validator:** LLM output indicates no policy violation, but expected knowledge article ID

**Trace:** `runs/crmarenapro/query7/commands.json`; `item_3`, `item_4`, `item_5`, `item_7`, `item_8`, `item_9`. Validator SHA-256: `6a3a4ce64de4fe3abbb7c38f50f0bd5c54ef09506445b384fa9f2f537bb0704e`.

### cve q10 — Identifier joins and identity

**Evidence status:** Unresolved. **Repair tested:** No.

Raw-ID join returns zero; later literal/fuzzy variants disagree. item_27 prints products 5 (the validator value), while the final answer is 14. Matching an intermediate scalar does not validate that join's semantics.

**Check/action:** Retain the product membership set for each mapping and compare variants; require final-answer provenance.

**Official validator:** expected 5

**Trace:** `runs/cve/query10/commands.json`; `item_13`, `item_20`, `item_27`, `item_29`, `item_30`, `item_31`. Validator SHA-256: `e4bd55f7fa4e930198f5c487cc7be28798576e74ba6ae4713d1d8a1857ffd6ab`.

### cve q2 — Cohort and aggregation

**Evidence status:** Supported. **Repair tested:** No.

The decisive vendor ranking counts known-ransomware entries without the required critical-severity intersection. Microsoft leads that broader set; the validator expects Fortinet.

**Check/action:** Check every required predicate is present and report cohort size before and after the critical-severity join.

**Official validator:** expected 'fortinet'

**Trace:** `runs/cve/query2/commands.json`; `item_5`, `item_6`, `item_7`, `item_8`, `item_9`, `item_10`, `item_11`. Validator SHA-256: `29ea555f29aba53d062ace211a197b6a1638c462134de8229363da0e63caf7cd`.

### cve q3 — Identifier joins and identity

**Evidence status:** Unresolved. **Repair tested:** No.

Approximate identifier normalization/matching is used for an anti-join, producing 1238 versus 1262. Exact false matches and unmatched CVEs are not reconciled.

**Check/action:** Use canonical identifiers and audit anti-join membership; avoid treating fuzzy similarity as identity without validation.

**Official validator:** expected 1262

**Trace:** `runs/cve/query3/commands.json`; `item_4`, `item_5`, `item_7`, `item_8`. Validator SHA-256: `e4bd55f7fa4e930198f5c487cc7be28798576e74ba6ae4713d1d8a1857ffd6ab`.

### cve q4 — Identifier joins and identity

**Evidence status:** Unresolved. **Repair tested:** No.

Noisy identifier exploration and incomplete calculations end with d-link versus ivanti. The trace does not isolate a validated vendor calculation that supports the final selection.

**Check/action:** Produce one reproducible joined vendor table and inspect unmatched keys before choosing a maximum.

**Official validator:** expected 'ivanti'

**Trace:** `runs/cve/query4/commands.json`; `item_4`, `item_5`, `item_6`, `item_7`, `item_8`, `item_9`. Validator SHA-256: `456d24a6c945e7f67c94892d3c4e3d5c04933253162c1ed13a614a29f151b2a9`.

### cve q5 — Extraction and representation

**Evidence status:** Supported. **Repair tested:** No.

The agent counts version-range bounds as versions (6), while the stored CPE version field is '*' and the validator expects 1. Version values and range endpoints are different units.

**Check/action:** Separate literal CPE version from start/end constraints; define the counting unit explicitly.

**Official validator:** expected 1

**Trace:** `runs/cve/query5/commands.json`; `item_4`, `item_5`, `item_6`, `item_7`, `item_8`, `item_9`. Validator SHA-256: `e4bd55f7fa4e930198f5c487cc7be28798576e74ba6ae4713d1d8a1857ffd6ab`.

### cve q6 — Identifier joins and identity

**Evidence status:** Unresolved. **Repair tested:** No.

Text-similarity thresholds replace a validated CVE-ID join. Candidate counts vary greatly (105 documents/59 KEV IDs at one threshold; 13 documents/12 IDs at another). Final 60 differs from validator 13.

**Check/action:** Audit one-to-many similarity matches and calibrate on labeled pairs; do not use a threshold-dependent count as a validated identity join.

**Official validator:** expected 13

**Trace:** `runs/cve/query6/commands.json`; `item_9`, `item_11`, `item_14`, `item_15`, `item_18`, `item_19`. Validator SHA-256: `e4bd55f7fa4e930198f5c487cc7be28798576e74ba6ae4713d1d8a1857ffd6ab`.

### cve q8 — Identifier joins and identity

**Evidence status:** Unresolved. **Repair tested:** No.

Digit-subsequence ID matching and colon-only CPE parsing give inconsistent intermediates (111 and 116); final 244 differs from validator 58 and lacks a verified matching output in the reviewed trace.

**Check/action:** Measure parse coverage, keep unmatched ID examples, and bind the final count to a reproducible membership set.

**Official validator:** expected 58

**Trace:** `runs/cve/query8/commands.json`; `item_11`, `item_14`, `item_15`, `item_16`. Validator SHA-256: `017fd5411ba3fc7687b398ff6dcec86afea0c5100f3ba57fb52abe6dfd8a933e`.

### cve q9 — Identifier joins and identity

**Evidence status:** Unresolved. **Repair tested:** No.

Rows are grouped by published/modified/status rather than a verified canonical CVE key. Similarity thresholds give counts from 8 upward; final 74 differs from expected 8. The matching scalar alone does not prove a correct threshold.

**Check/action:** Require canonical identity and report join collisions; inspect threshold sensitivity rather than selecting a count that matches the answer key.

**Official validator:** expected 8

**Trace:** `runs/cve/query9/commands.json`; `item_17`, `item_18`, `item_19`, `item_20`, `item_21`, `item_22`. Validator SHA-256: `e4bd55f7fa4e930198f5c487cc7be28798576e74ba6ae4713d1d8a1857ffd6ab`.

### imdb q5 — Cohort and aggregation

**Evidence status:** Supported. **Repair tested:** No.

The search stops at the first company and returns that row's rating/title. The task requires independent minima across the qualifying set; rating 6.5 misses the required 1.0.

**Check/action:** Compute each requested minimum over the full qualifying set; warn about break/early return before all aggregates finish.

**Official validator:** Rating '1.0' not found in LLM output.

**Trace:** `runs/imdb/query5/commands.json`; `item_8`, `item_9`, `item_10`, `item_11`, `item_12`. Validator SHA-256: `eb437c2a2f0e625870d874be4f570979d18793076937edffe25fdace34a3f91f`.

### imdb q6 — Extraction and representation

**Evidence status:** Supported. **Repair tested:** No.

The workflow copies identifiers from column-formatted output into manual lists (e.g. shortened 18180 versus 1818030), then restricts candidate people. Final Bridget/Monster House misses Lola/Hoodwinked. Candidate loss is visible; a corrected full result has not been replayed.

**Check/action:** Keep joins machine-readable; reject copied/truncated identifiers and compare candidate counts after manual transfer.

**Official validator:** Character name 'Lola' not found in LLM output.

**Trace:** `runs/imdb/query6/commands.json`; `item_20`, `item_24`, `item_25`, `item_26`, `item_27`, `item_28`, `item_29`, `item_30`. Validator SHA-256: `da0339de482eac9949b3b98407ba2601d6538f6bbee99776c855f9e6362d9ca4`.

### imdb q9 — Cohort and aggregation

**Evidence status:** Unresolved. **Repair tested:** No.

The question explicitly asks for the alphabetically first vote count. The computed string minimum is 101188; the validator requires 1040. Genre, writer and title match. This may be a sort/cohort or task-validator ambiguity, not an established model error.

**Check/action:** Compare numeric and lexicographic minima on the exact qualifying set and adjudicate the wording; retain the official failed score meanwhile.

**Official validator:** Vote count '1040' not found in LLM output.

**Trace:** `runs/imdb/query9/commands.json`; `item_17`, `item_28`, `item_30`. Validator SHA-256: `00014b7a06b4b54f51b87cc4eb3313433734e938f72d2ad9c300ca3529366cc8`.

### krama q10 — Temporal state and status

**Evidence status:** Unresolved. **Repair tested:** No.

An initial epoch parse is corrected. The final May 10-13 window uses 14 rows and mean 0.000707776 (reported 0.000708), versus 0.000748. The exact storm-window boundary remains unresolved.

**Check/action:** Derive start/end instants from the specified storm series and reconcile included TLE epochs before averaging.

**Official validator:** Found numbers ['10', '13', '2024.', '14', '43180'], but expected 0.000748 (±5e-07)

**Trace:** `runs/krama/query10/commands.json`; `item_9`, `item_13`, `item_14`, `item_15`. Validator SHA-256: `e16c6a925ac09b46dd70d3ba4c41a2f17c540845542ac50c9540ab27e1e2c4cd`.

### krama q2 — Execution and unsupported result

**Evidence status:** Supported. **Repair tested:** No.

Spatial dependencies are unavailable, a custom parser fails on an empty sequence, and later temporary-script/envelope attempts do not establish a successful state intersection. Final Wyoming differs from Idaho.

**Check/action:** Block a confident spatial answer without a successful geometry result; validate geometry parsing and intersections, then rerun the calculation.

**Official validator:** Found states ['Wyoming'], but expected 'Idaho'

**Trace:** `runs/krama/query2/commands.json`; `item_14`, `item_15`, `item_16`, `item_17`, `item_18`, `item_19`. Validator SHA-256: `4558b5fdcffc364de56afa8d0d998a0a9c1e5041bfbe7e11e910f224eb241df2`.

### krama q3 — Cohort and aggregation

**Evidence status:** Supported. **Repair tested:** No.

A 55-region computation gives 713068/55 = 12964.872727, matching the validator. The final answer includes San Juan, giving 714110/56 = 12751.9643. Inclusion of San Juan is the observed cohort difference; task interpretation still needs justification.

**Check/action:** Show cohort membership and territorial inclusion rules; trace the final scalar to its selected computation.

**Official validator:** Found numbers ['12', '751.9643', '2023', '2020', '0.75'], but expected 12964.8727 (±5e-05)

**Trace:** `runs/krama/query3/commands.json`; `item_15`, `item_16`, `item_17`, `item_18`. Validator SHA-256: `65bd9b052c7eaeb4a495643232d1a751f2e0327300c350f0b6a10cfd2719832d`.

### krama q6 — Extraction and representation

**Evidence status:** Unresolved. **Repair tested:** No.

After revising an initial violation parser, the answer uses 4/97 = 4.12% versus 3.88%. Text negation, sampling dates and eligible-row denominator need reconciliation; the exact differing rows are not established.

**Check/action:** Retain per-sample dates and explicit pass/fail labels, including negation; verify denominator and missing records.

**Official validator:** Found numbers ['10.55', '2008', '2016', '4.12', '4'], but expected 3.88 (±0.1)

**Trace:** `runs/krama/query6/commands.json`; `item_8`, `item_9`, `item_10`, `item_11`. Validator SHA-256: `7cfb29e674217cb8139f9d1e7ca0a5b4be2f12b55462861ae04cda21aec28472`.

### krama q7 — Identifier joins and identity

**Evidence status:** Supported. **Repair tested:** No.

The last computation uses positional zip(ages, values) and protein > 0 as hyperactivation, producing 62 patients with mean 63.82 versus 60. Both alignment and the domain threshold are unverified assumptions.

**Check/action:** Join by patient ID, assert one-to-one alignment, and use the documented CDK12 hyperactivation definition.

**Official validator:** Found numbers ['63.82', '62', '12'], but expected 60.0 (±0.005)

**Trace:** `runs/krama/query7/commands.json`; `item_22`, `item_23`, `item_24`, `item_25`. Validator SHA-256: `408397697ea66e9a926da1cb38153ef77e5da250d681c40402fa925fe25deb46`.

### krama q9 — Final-answer rounding

**Evidence status:** Supported. **Repair tested:** No.

October is selected correctly. The tool computes 18177/(744*10) = 2.4431451613, which rounds to 2.4431 at four decimals. The final answer says 2.4432 and fails the unchanged tolerance.

**Check/action:** Format the computed scalar directly at the requested precision; check final-answer equality against the cited tool value.

**Official validator:** Found numbers ['2024.', '2', '2.4432'], but expected 2.4431 (±5e-05)

**Trace:** `runs/krama/query9/commands.json`; `item_15`, `item_18`. Validator SHA-256: `febd2ee2ea8e23a511dbb2df2666f1418bdcd4df23cabf75733e8ec3f4d198a8`.

### stockmarket q4 — Cohort and aggregation

**Evidence status:** Unresolved. **Repair tested:** No.

The agent ranks by up-day count, then net up-minus-down count. Its top five differ from the validator. The question's top-five ranking interpretation has not been independently resolved.

**Check/action:** Specify the ranking metric and inspect the full candidate order and ties before attributing the mismatch to one algorithm.

**Official validator:** Name not found within 5 edits: 'MFA Financial, Inc', closest: 'rnational, inc' (distance=8)

**Trace:** `runs/stockmarket/query4/commands.json`; `item_3`, `item_4`. Validator SHA-256: `09538392d54f1c68d9aac70e5d7d1c692cebe3a743078067b211bbf0909d7f8d`.

### usaspending q1 — Extraction and representation

**Evidence status:** Unresolved. **Repair tested:** No.

Primary-row selection and regex/qualitative interpretation of prose dollar amounts give 900 versus 898. Many amounts need interpretation; the exact two discrepant awards are not established.

**Check/action:** Separate explicit numeric parses from inferred ranges; audit awards near the threshold and superseded amount records.

**Official validator:** expected 898

**Trace:** `runs/usaspending/query1/commands.json`; `item_10`, `item_11`, `item_12`, `item_13`, `item_14`, `item_15`. Validator SHA-256: `274c8c28b74c1f485efd7e0d0649948eec0909f36593d96888b52fa7d4c6e52e`.

### usaspending q2 — Identifier joins and identity

**Evidence status:** Unresolved. **Repair tested:** No.

Recipient and award joins use inconsistent normalization, while prose filtering excludes numeric forms. The result is 61 versus 75; the exact fourteen missed awards are not isolated.

**Check/action:** Reconcile normalized UEIs and award IDs, then audit amount representation and threshold eligibility row by row.

**Official validator:** expected 75

**Trace:** `runs/usaspending/query2/commands.json`; `item_9`, `item_10`, `item_11`, `item_12`, `item_13`, `item_14`. Validator SHA-256: `274c8c28b74c1f485efd7e0d0649948eec0909f36593d96888b52fa7d4c6e52e`.

### usaspending q5 — Extraction and representation

**Evidence status:** Unresolved. **Repair tested:** No.

Any qualifying amount row and numeric/figure-word heuristics yield 11 normalized sectors versus 12. The missing sector and the effect of superseded amount rows are unresolved.

**Check/action:** Define the authoritative amount record, keep parse confidence and list sector membership with contributing awards.

**Official validator:** expected 12

**Trace:** `runs/usaspending/query5/commands.json`; `item_12`, `item_13`, `item_14`, `item_15`, `item_16`, `item_17`. Validator SHA-256: `274c8c28b74c1f485efd7e0d0649948eec0909f36593d96888b52fa7d4c6e52e`.

### usaspending q6 — Identifier joins and identity

**Evidence status:** Unresolved. **Repair tested:** No.

Aggressive corporate-suffix/punctuation removal changes company grouping (52 then 57 versus 56); record counts are not a verified count of distinct normalized UEIs. Exact merges/splits remain open.

**Check/action:** Audit name collisions and count distinct legal identifiers within each alias group rather than raw records.

**Official validator:** expected 56

**Trace:** `runs/usaspending/query6/commands.json`; `item_4`, `item_5`, `item_6`. Validator SHA-256: `274c8c28b74c1f485efd7e0d0649948eec0909f36593d96888b52fa7d4c6e52e`.

### usaspending q8 — Identifier joins and identity

**Evidence status:** Unresolved. **Repair tested:** No.

Broad Lockheed name matching, OCR-style UEI normalization, raw award-ID joining and ambiguous prose amounts produce 23 versus 25. No exact two-award reconciliation is available.

**Check/action:** Review subsidiary scope, canonical join keys and ambiguous threshold amounts in the difference set.

**Official validator:** expected 25

**Trace:** `runs/usaspending/query8/commands.json`; `item_5`, `item_6`, `item_7`, `item_8`. Validator SHA-256: `274c8c28b74c1f485efd7e0d0649948eec0909f36593d96888b52fa7d4c6e52e`.

### usaspending q9 — Extraction and representation

**Evidence status:** Unresolved. **Repair tested:** No.

First-ctid amount selection, exact English-language filtering and manually interpreted amounts produce 142 versus 147. The five discrepant awards are not identified.

**Check/action:** Select authoritative amount versions, normalize language labels and expose per-award eligibility decisions.

**Official validator:** expected 147

**Trace:** `runs/usaspending/query9/commands.json`; `item_7`, `item_8`, `item_9`, `item_10`, `item_11`. Validator SHA-256: `274c8c28b74c1f485efd7e0d0649948eec0909f36593d96888b52fa7d4c6e52e`.

### yelp q2 — Cohort and aggregation

**Evidence status:** Supported. **Repair tested:** No.

Actual review rows identify PA: 662 reviews, mean 3.699396. Business metadata review_count instead favors MO (2243 versus PA 2022). The final answer chooses MO 3.9061; the validator expects PA 3.7.

**Check/action:** Check that the ranking count and average are computed from the same requested review population, not mixed metadata and sample rows.

**Official validator:** No occurrence of 3.7 near PA/Pennsylvania.

**Trace:** `runs/yelp/query2/commands.json`; `item_7`, `item_8`. Validator SHA-256: `aa1e9fe46484d1319fe7da725441e34d6c2008672a990ccc8424b75fa19a582b`.

### yelp q3 — Extraction and representation

**Evidence status:** Unresolved. **Repair tested:** No.

A raw-string 2018 date filter yields 36 businesses; decoded parking conditions reduce this to 21 versus 35. This run does not show the screenshot's five-row output-cap failure. Date-format and parking interpretation remain hypotheses.

**Check/action:** Parse review dates and parking flags explicitly; report qualifying counts after each filter and reconcile omitted businesses.

**Official validator:** Number 35 not found in LLM output.

**Trace:** `runs/yelp/query3/commands.json`; `item_4`, `item_5`, `item_6`. Validator SHA-256: `c79185af0b0bc5d163d2c617fc853f724ecf30142e903978363e7ad82a4fb4ee`.

### yelp q7 — Semantic classification

**Evidence status:** Unresolved. **Repair tested:** No.

User/review date filters and manually extracted business categories produce a top set missing Breakfast & Brunch. Exact label and date membership differences remain unresolved.

**Check/action:** Audit category extraction coverage and normalized dates, then compare category-level membership near the top-five cutoff.

**Official validator:** Missing category: Breakfast & Brunch

**Trace:** `runs/yelp/query7/commands.json`; `item_3`, `item_4`, `item_5`. Validator SHA-256: `b35b9f67c8c915c9e06d02b1abacfe853655b45cb34aef30e5ee972d84a21caf`.

