# Method conditions vs the Haiku baseline (104 questions; baseline 2 trials, each method 1 trial)

Same questions, prompts, sandbox and original validators; Haiku as the agent and as every LLM inside the methods.
Accuracy = correct / scored per trial. "Fixed" = a question Haiku got wrong in both baseline trials that the
condition got right in at least one of its trials; "Lost" = right in both baseline trials, wrong in every condition trial.
Pass@k uses the condition's own number of trials (k = 2 for the baseline, 1 for a single-trial condition).

| Condition | Trials | Accuracy per trial (scored) | Mean | Pass@k | Fixed (target category) | Fixed (other) | Lost | Agent cost (USD, all trials) |
|---|---|---|---|---|---|---|---|---|
| Haiku baseline | 2 | 63.5% (104) / 60.6% (104) | 62.0% | 69.2% | 0 | 0 | 0 | 7.43 |
| fdj (Identifier joins and identity) | 1 | 58.7% (104) | 58.7% | 58.7% | 1 cve q6 | 5 DEPS_DEV_V1 q2, PATENTS q3, crmarenapro q13, krama q4, stockmarket q4 | 9 GITHUB_REPOS q2, bookreview q3, crmarenapro q3, crmarenapro q4, imdb q2, krama q3, krama q8, krama q10, usaspending q8 | 3.27 |
| docetl (Extraction and representation) | 1 | 64.4% (104) | 64.4% | 64.4% | 1 DEPS_DEV_V1 q2 | 5 crmarenapro q13, googlelocal q3, krama q4, music_brainz_20k q1, stockmarket q4 | 3 civic_unstructured q8, krama q8, music_brainz_20k q3 | 2.61 |
| sqlverify (Cohort / temporal) | 1 | 68.3% (104) | 68.3% | 68.3% | 4 crmarenapro q13, imdb q9, krama q4, stockmarket q4 | 2 krama q6, music_brainz_20k q1 | 1 crmarenapro q4 | 3.52 |

## Haiku both-runs-wrong questions by review category

| Category | Questions | fdj fixed | docetl fixed | sqlverify fixed |
|---|---|---|---|---|
| Answer format vs validator | 4 | 1 | 1 | 0 |
| Cohort and aggregation | 5 | 3 | 3 | 4 |
| Execution and unsupported result | 5 | 0 | 0 | 0 |
| Extraction and representation | 3 | 1 | 1 | 0 |
| Identifier joins and identity | 8 | 1 | 1 | 1 |
| Semantic classification | 4 | 0 | 0 | 1 |
| Temporal state and status | 3 | 0 | 0 | 0 |

## sqlverify: verifier verdicts (1 trial(s)) and the second round

- Questions with no verifiable SQL (MongoDB / Python only / multi-database): 95
- Round-1 wrong: rejected 3, accepted 0 (false accepts)
- Round-1 right: rejected 6 (false rejects), accepted 0
- Second round: wrong->right 2, wrong->wrong 1, right->wrong 0, right->right 6
- Round-1 accuracy (before any second round): trial 1 66.3%

## Where each method acted (single trial vs the two baseline trials)

| Condition | Acted on | Correct (condition / baseline t1 / t2) | Untouched | Correct (condition / baseline t1 / t2) |
|---|---|---|---|---|
| fdj | 23 | 8 / 12 / 9 | 81 | 53 / 54 / 54 |
| docetl | 22 | 6 / 7 / 7 | 82 | 61 / 59 / 56 |
| sqlverify | 9 | 8 / 6 / 6 | 95 | 63 / 60 / 57 |

## fdj preprocessing (once per dataset, Haiku)

- LLM cost estimate: $14.72
- civic_unstructured/funding_project_names: status=ok, left_size=99, matches=58, clusters=59, refined=True
- usaspending/amounts_to_contracts: status=ok, left_size=9921, right_size=9921, matches=97422, refined=False
- usaspending/documents_to_contracts: status=ok, left_size=9921, right_size=9921, matches=56190, refined=False
- usaspending/recipients_to_contracts: status=ok, left_size=3317, right_size=3317, matches=3317, refined=False
- music_brainz_20k/track_duplicates: status=ok, left_size=19375, matches=14684, clusters=10492, refined=False
- cve/kev_to_vulns: status=failed, left_size=1583, right_size=75199, error=BudgetExceeded: budget $7.20 reached (spent $7.2027; fdj.label)
- cve/cvss_to_vulns: status=failed, left_size=68367, right_size=75199, error=BudgetExceeded: budget $9.70 reached (spent $9.7053; fdj.label)
- cve/descriptions_to_vulns: status=failed, left_size=71501, right_size=75199, error=BudgetExceeded: budget $12.21 reached (spent $12.2164; fdj.label)
- cve/cpe_to_vulns: status=failed, left_size=549689, right_size=75199, error=BudgetExceeded: budget $14.72 reached (spent $14.7184; fdj.label)

## docetl preprocessing (once per dataset, Haiku)

- LLM cost estimate: $1.39
- DEPS_DEV_V1/project_metrics: status=ok, rows=770
- cve/cvss_scores: status=ok, rows=68367
- usaspending/award_amounts: status=ok, rows=10266
- usaspending/recipient_totals: status=ok, rows=3317
- usaspending/agency_totals: status=ok, rows=47
