# claude-haiku-5-5 DataAgentBench — complete 104-task evaluation

One independent trial per original question, descriptions+hints. Original query-specific validators. Pass@5 is not available. Claude Code CLI harness (the paper evaluated Claude models with Claude Code); not the authors exact driver. Offline/connection tests are excluded. Infrastructure failures are separate from wrong answers.

**Correct: 63/104 scored; unscored: 0; coverage: 104/104.**

Dataset-macro Pass@1: 60.10%. Question-weighted accuracy: 60.58%. Pass@5: unavailable.

Recorded input tokens: 64,052,046; cached input: 59,351,220; output: 2,146,405; tool calls: 1,686. Dollar cost: unavailable. Excluded attempts are accounted for separately in attempt-accounting.json.

| Dataset | Scored | Correct | Accuracy | Unscored |
|---|---:|---:|---:|---:|
| DEPS_DEV_V1 | 2 | 0 | 0.00% | 0 |
| GITHUB_REPOS | 4 | 3 | 75.00% | 0 |
| PANCANCER_ATLAS | 3 | 1 | 33.33% | 0 |
| PATENTS | 3 | 1 | 33.33% | 0 |
| agnews | 4 | 3 | 75.00% | 0 |
| bookreview | 3 | 3 | 100.00% | 0 |
| civic_unstructured | 10 | 2 | 20.00% | 0 |
| crmarenapro | 13 | 10 | 76.92% | 0 |
| cve | 10 | 2 | 20.00% | 0 |
| googlelocal | 4 | 2 | 50.00% | 0 |
| imdb | 10 | 9 | 90.00% | 0 |
| krama | 10 | 8 | 80.00% | 0 |
| music_brainz_20k | 3 | 2 | 66.67% | 0 |
| stockindex | 3 | 3 | 100.00% | 0 |
| stockmarket | 5 | 4 | 80.00% | 0 |
| usaspending | 10 | 5 | 50.00% | 0 |
| yelp | 7 | 5 | 71.43% | 0 |

## Failure review

0 failed questions have selected trace-based reviews. This is not an exhaustive semantic adjudication. Official grades are unchanged. See failure_analysis.csv and review-notes.json for evidence.
