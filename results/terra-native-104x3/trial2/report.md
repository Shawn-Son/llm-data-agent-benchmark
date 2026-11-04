# gpt-5.6-terra DataAgentBench — partial evaluation

One independent trial per original question, descriptions+hints. Original query-specific validators. Pass@5 is not available. Authors native Codex driver was unavailable; this is a documented Codex CLI reconstruction. Offline/connection tests are excluded. Infrastructure failures are separate from wrong answers.

**Correct: 43/82 scored; unscored: 22; coverage: 104/104.**

Dataset-macro Pass@1: 64.63%. Question-weighted accuracy: 52.44%. Pass@5: unavailable.

Recorded input tokens: 26,801,224; cached input: 10,982,882; output: 419,083; tool calls: 947. Dollar cost: unavailable. Excluded attempts are accounted for separately in attempt-accounting.json.

| Dataset | Scored | Correct | Accuracy | Unscored |
|---|---:|---:|---:|---:|
| DEPS_DEV_V1 | 2 | 1 | 50.00% | 0 |
| GITHUB_REPOS | 4 | 3 | 75.00% | 0 |
| PANCANCER_ATLAS | 3 | 2 | 66.67% | 0 |
| PATENTS | 3 | 3 | 100.00% | 0 |
| agnews | 4 | 1 | 25.00% | 0 |
| bookreview | 3 | 3 | 100.00% | 0 |
| civic_unstructured | 10 | 4 | 40.00% | 0 |
| crmarenapro | 13 | 6 | 46.15% | 0 |
| cve | 10 | 0 | 0.00% | 0 |
| googlelocal | 4 | 4 | 100.00% | 0 |
| imdb | 9 | 6 | 66.67% | 1 |
| krama | 9 | 3 | 33.33% | 1 |
| music_brainz_20k | 2 | 2 | 100.00% | 1 |
| stockindex | 3 | 3 | 100.00% | 0 |
| stockmarket | 3 | 2 | 66.67% | 2 |
| usaspending | 0 | 0 | N/A | 10 |
| yelp | 0 | 0 | N/A | 7 |

## Failure review

0 failed questions have selected trace-based reviews. This is not an exhaustive semantic adjudication. Official grades are unchanged. See failure_analysis.csv and review-notes.json for evidence.
