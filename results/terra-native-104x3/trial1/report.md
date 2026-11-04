# gpt-5.6-terra DataAgentBench — partial evaluation

One independent trial per original question, descriptions+hints. Original query-specific validators. Pass@5 is not available. Authors native Codex driver was unavailable; this is a documented Codex CLI reconstruction. Offline/connection tests are excluded. Infrastructure failures are separate from wrong answers.

**Correct: 61/103 scored; unscored: 1; coverage: 104/104.**

Dataset-macro Pass@1: 66.82%. Question-weighted accuracy: 59.22%. Pass@5: unavailable.

Recorded input tokens: 33,090,075; cached input: 13,505,252; output: 530,115; tool calls: 1,152. Dollar cost: unavailable. Excluded attempts are accounted for separately in attempt-accounting.json.

| Dataset | Scored | Correct | Accuracy | Unscored |
|---|---:|---:|---:|---:|
| DEPS_DEV_V1 | 1 | 1 | 100.00% | 1 |
| GITHUB_REPOS | 4 | 2 | 50.00% | 0 |
| PANCANCER_ATLAS | 3 | 2 | 66.67% | 0 |
| PATENTS | 3 | 2 | 66.67% | 0 |
| agnews | 4 | 1 | 25.00% | 0 |
| bookreview | 3 | 3 | 100.00% | 0 |
| civic_unstructured | 10 | 3 | 30.00% | 0 |
| crmarenapro | 13 | 10 | 76.92% | 0 |
| cve | 10 | 1 | 10.00% | 0 |
| googlelocal | 4 | 3 | 75.00% | 0 |
| imdb | 10 | 6 | 60.00% | 0 |
| krama | 10 | 7 | 70.00% | 0 |
| music_brainz_20k | 3 | 3 | 100.00% | 0 |
| stockindex | 3 | 3 | 100.00% | 0 |
| stockmarket | 5 | 4 | 80.00% | 0 |
| usaspending | 10 | 4 | 40.00% | 0 |
| yelp | 7 | 6 | 85.71% | 0 |

## Failure review

0 failed questions have selected trace-based reviews. This is not an exhaustive semantic adjudication. Official grades are unchanged. See failure_analysis.csv and review-notes.json for evidence.
