# Live evaluation with claude-haiku-5-5

Spend (estimate): $2.083; calls 6821 (+288 cached)

## SQL verifiers (A = accept, R = reject)

| case | kind | rt | se | sc | cohort | AND | OR |
|---|---|---|---|---|---|---|---|
| crmarenapro_q12_date_field | right | R | R | R | R | R | R |
| crmarenapro_q12_date_field | wrong | A | R | A | R | R | A |
| civic_q4_inclusive_end | right | A | A | A | A | A | A |
| civic_q4_inclusive_end | wrong | R | R | R | R | R | R |
| imdb_keyword_join_leading_zeros | right | A | A | A | A | A | A |
| imdb_keyword_join_leading_zeros | wrong | R | R | R | A | R | A |

| method | false accepts | false rejects |
|---|---|---|
| rt | 1/3 | 1/3 |
| se | 0/3 | 1/3 |
| sc | 1/3 | 1/3 |
| cohort | 1/3 | 1/3 |
| and | 0/3 | 1/3 |
| or | 2/3 | 1/3 |

## Extraction fallback: usaspending prose amounts: 60 rows sent to Haiku, 0 got a value (should be 0)
DEPS naive pattern misses: 60 rows sent to Haiku, 60 agree with the code extraction

## DocETL optimizer on DEPS: plan = original, gate = {'needs_improvement': False, 'reasons': []}, ratings = None, wins = None

## FDJ on cve with Haiku
features: ['raw_similarity (code/code, token_jaccard)', 'cve_year_sequence_pair (code/code, digit_edit)', 'confusable_digit_sequence (code/code, digit_edit)', 'normalized_cve_year (llm/code, numeric_abs)', 'bare_sequence_candidate (code/code, digit_edit)']
decomposition: (raw_similarity <= 1); T' = 1.000; feasible = True
labelled pairs 1594; Haiku label agreement with oracle {'n': 1594, 'agree': 1516}
candidates 400000 of 400000 pairs; candidate recall 1.000, precision 0.000; refined = {'skipped': '400000 candidates exceed the cap of 20000 or the budget'}
