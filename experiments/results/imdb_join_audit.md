# imdb identifier join audit (offline)

keyword rows: 134170, movie_keyword rows: 4523930

| rule | matched keys | left unmatched rows | right unmatched rows |
|---|---:|---:|---:|
| raw | 0 | 134170 | 4523930 |
| strip_hash_case | 0 | 134170 | 4523930 |
| numeric_id | 134170 | 0 | 0 |
| ocr_fold_digits | 0 | 134170 | 4523930 |

Warnings:
- match count swings with the key rule: raw=0 vs numeric_id=134170; canonicalise keys (numeric_id) before joining
- movie_keyword.keyword_id: >20% of keys are zero-padded numbers behind a prefix; compare as integers, not digit strings

q10 keyword filter: digit-string rule links 2371 movies, numeric-id rule links 21046 movies.
