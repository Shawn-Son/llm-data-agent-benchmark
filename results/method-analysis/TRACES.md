# Trace-level analysis of the method conditions

Generated on Great Lakes by `experiments/analyze_method_traces.py` (full JSON with answer tails and delivered-output
samples: `~/cl/traces.json` there; regenerate with the command in the script docstring). Rows: every question where a
method acted, plus every question whose outcome differs from both baseline trials. "Agent use of outputs" counts tool
calls that touch `dabcheck_prep/` and calls that load an output file with code (pattern match on tool inputs).
"Answer says" quotes the final answer where it mentions the method outputs.

## Prompt identity with the baseline (prompt.txt sha256 vs baseline trial 1)

- fdj: untouched same 81, acted different 23 (the prompt note)
- docetl: untouched same 82, acted different 22
- sqlverify: untouched same 95, acted same 9 (round 1 prompt unchanged; the second round is a new session)

## fdj

| Question | Acted | Result (cond / base t1 / t2) | Agent use of outputs | Condition grader reason | Answer says |
|---|---|---|---|---|---|
| DEPS_DEV_V1 q2 | False | True / False / False | | All project names found. | |
| GITHUB_REPOS q2 | False | False / True / True | | No fuzzy match found for 'swiftandroid/swift' within 3-character distance | |
| PATENTS q3 | False | True / False / False | | All assignee-title pairs matched successfully by at least one method. | |
| bookreview q3 | False | False / True / True | | Missing book title in LLM output: Clark the Shark: Tooth Trouble, No. 1 | |
| civic_unstructured q1 | True | True / True / True | 2 calls, 1 loads, README True | All ground truth project names found in LLM output (entity-resolved). | Where I departed from the precomputed joins (FDJ); FDJ put "PCH Median Improvements at Paradise Cove and Zuma Beach" in the same cluster |
| civic_unstructured q10 | True | False / True / False | 2 calls, 1 loads, README True | Ground truth '0.69' (tol=0.01) not found in LLM output: Answer: 0.63 | I did not accept the FDJ clusters blindly |
| civic_unstructured q2 | True | False / False / False | 2 calls, 1 loads, README True | Missing in LLM output: amount '13460000' | The precomputed FDJ file puts four funding names in one cluster: citywide_guardrail_replacement, guardrail_replacement_citywide, ... |
| civic_unstructured q3 | True | False / False / False | 3 calls, 1 loads, README True | Ground truth is empty, but output lists funding source(s) | FDJ join file: I did not rely on it |
| civic_unstructured q4 | True | False / True / False | 2 calls, 0 loads, README True | Ground truth '0.34' (tol=0.01) not found in LLM output: Answer: 0.29 | I matched funding names to agenda titles by hand, using the FDJ clusters as a guide |
| civic_unstructured q5 | True | False / False / False | 2 calls, 0 loads, README True | Ground truth '4401352.94' (tol=0.1) not found: Answer: $4,253,066.67 | I used the FDJ clusters as a starting point, but overrode them where they conflicted with the agendas |
| civic_unstructured q6 | True | False / False / False | 4 calls, 3 loads, README True | Missing in LLM output: amount '88615000' | Precomputed join not used for the final numbers; the FDJ cluster file merges genuinely different projects |
| civic_unstructured q7 | True | False / False / False | 2 calls, 1 loads, README True | Ground truth is empty, but output names project(s) | I used the precomputed FDJ name clusters only as a reference |
| civic_unstructured q8 | True | True / True / True | 2 calls, 1 loads, README True | Ground truth project name and amount found | Malibu Park Drainage Improvements ... (same project per the FDJ cluster) |
| civic_unstructured q9 | True | True / True / False | 2 calls, 1 loads, README True | All ground truth funding sources found | I did not take the precomputed FDJ clusters at face value |
| crmarenapro q13 | False | True / False / False | | Found expected agent ID | |
| crmarenapro q3 | False | False / True / True | | Found stages ['Quote'], but expected 'Negotiation' | |
| crmarenapro q4 | False | False / True / True | | Found months ['March', 'June'], but expected 'November' | |
| cve q6 | False | True / False / False | | matched 13 | |
| imdb q2 | False | False / True / True | | Title '#1 Cheerleader Camp' not found in LLM output. | |
| krama q10 | False | False / True / True | | Found numbers [...], but expected 0.000748 | |
| krama q3 | False | False / True / True | | Found numbers [...], but expected 12964.8727 | |
| krama q4 | False | True / False / False | | Found expected value: 319655 | |
| krama q8 | False | False / True / True | | Found protein-like tokens [...], but expected 'PFN1' | |
| music_brainz_20k q1 | True | False / False / False | 3 calls, 1 loads, README True | Ground truth '1059.46' not found: $601.44 | The FDJ file places all four records in the same cluster, which agrees with my title-based matching; used only to confirm |
| music_brainz_20k q2 | True | True / True / True | 4 calls, 3 loads, README True | Ground truth found | The FDJ file put all three IDs in the same duplicate cluster, which matches my own comparison |
| music_brainz_20k q3 | True | True / True / True | 7 calls, 5 loads, README True | Fuzzy match found | FDJ precomputed joins: not used for the answer; I checked the FDJ duplicate clusters and they are unreliable |
| stockmarket q4 | False | True / False / False | | All names matched | |
| usaspending q1 | True | False / False / False | 5 calls, 4 loads, README True | expected 898 | I did not use the FDJ amount pairs |
| usaspending q10 | True | True / True / True | 4 calls, 1 loads, README True | matched 141 | FDJ files: I did not use the precomputed join files |
| usaspending q2 | True | False / True / False | 12 calls, 11 loads, README True | expected 75 | I used the FDJ recipient mapping; I didn't use the FDJ amounts file, since it links each award to about 10 candidates |
| usaspending q3 | True | True / True / True | 4 calls, 2 loads, README True | matched 601 | Mapped raw strings to recipients_db UEIs using fdj_recipients_to_contracts; cross-checked with a deterministic key |
| usaspending q4 | True | False / False / True | 3 calls, 2 loads, README True | expected 'department of homeland security' | The FDJ amounts-to-contracts file is unreliable here |
| usaspending q5 | True | False / False / False | 3 calls, 1 loads, README True | expected 12 | This matched all 9,921 contracts to amount entries one-to-one, so I did not need the precomputed FDJ joins |
| usaspending q6 | True | False / False / False | 1 calls, 0 loads, README True | expected 56 | I did not use the precomputed FDJ files |
| usaspending q7 | True | True / True / True | 3 calls, 2 loads, README True | matched 23 | I did not use the FDJ amount file: it maps single IDs to up to 10 different awards |
| usaspending q8 | True | False / True / True | 6 calls, 3 loads, README True | expected 25 | Stripping non-alphanumeric characters and uppercasing gave an exact match for all 10,266 amount rows, so I did not need the FDJ joins |
| usaspending q9 | True | False / False / False | 3 calls, 2 loads, README True | expected 147 | I didn't need the FDJ pairs |

## docetl

| Question | Acted | Result (cond / base t1 / t2) | Agent use of outputs | Condition grader reason | Answer says |
|---|---|---|---|---|---|
| DEPS_DEV_V1 q1 | True | False / False / False | 3 calls, 1 loads, README True | Missing or mis-versioned above-cutoff package | The precomputed DocETL star counts for these five projects match the parsed values |
| DEPS_DEV_V1 q2 | True | True / False / False | 6 calls, 5 loads, README True | All project names found. | I checked the precomputed docetl_project_metrics; the results do not depend on the DocETL file |
| civic_unstructured q8 | False | False / True / True | | Missing project name 'City Hall Roof Replacement', amount '1340000' | |
| crmarenapro q13 | False | True / False / False | | Found expected agent ID | |
| cve q1 | True | False / False / False | 1 calls, 0 loads, README True | expected 4 | The DocETL output only covers CVSS scores, so it doesn't help with this query |
| cve q10 | True | False / False / False | 1 calls, 0 loads, README True | expected 5 | (mentions the CVSS file) |
| cve q2 | True | True / True / True | 1 calls, 0 loads, README True | matched 'fortinet' | The docetl CSV only covers cvss_score and didn't help with the ID join |
| cve q3 | True | False / False / False | 1 calls, 0 loads, README True | expected 1262 | The DocETL extractions only cover CVSS scores, so they did not help with the CVE key problem |
| cve q4 | True | False / False / False | 3 calls, 2 loads, README True | expected 'ivanti' | It matched the DocETL CSV on all 68,367 rows; not used to resolve the CVE keys |
| cve q5 | True | False / False / False | 1 calls, 0 loads, README True | expected 1 | The DocETL prep only covers CVSS scores, so it didn't contribute here |
| cve q6 | True | False / False / False | 1 calls, 0 loads, README True | expected 13 | The DocETL extractions only cover CVSS scores, so they don't help here |
| cve q7 | True | False / False / True | 1 calls, 0 loads, README True | expected 'cisco:adaptive_security_appliance_software' | (mentions the CVSS file) |
| cve q8 | True | False / False / False | 4 calls, 3 loads, README True | expected 58 | The DocETL score file gives 30,801 rows with a score >= 7; these are rows, not distinct CVEs |
| cve q9 | True | False / True / False | 1 calls, 0 loads, README True | expected 8 | The precomputed extractions cover CVSS scores only, so they do not help with the ID join |
| googlelocal q3 | False | True / False / False | | All businesses validated successfully. | |
| krama q4 | False | True / False / False | | Found expected value: 319655 | |
| krama q8 | False | False / True / True | | expected 'PFN1' | |
| music_brainz_20k q1 | False | True / False / False | | Ground truth found in LLM output. | |
| music_brainz_20k q3 | False | False / True / True | | No fuzzy match ("Groovey" by Rich Matteson, $5,668.50) | |
| stockmarket q4 | False | True / False / False | | All names matched | |
| usaspending q1 | True | False / False / False | 3 calls, 1 loads, README True | expected 898 | The DocETL extractions were not used, since they cover only ~7% of amounts |
| usaspending q10 | True | True / True / True | 2 calls, 0 loads, README True | matched 141 | I didn't use the DocETL extractions |
| usaspending q2 | True | False / True / False | 2 calls, 1 loads, README True | expected 75 | The amount file only parsed the same numeric rows I parsed myself (681 code values, no LLM ones) |
| usaspending q3 | True | True / True / True | 1 calls, 0 loads, README True | matched 601 | Not used |
| usaspending q4 | True | False / False / True | 6 calls, 3 loads, README True | expected 'department of homeland security' | I did not use the DocETL amount extraction |
| usaspending q5 | True | False / False / False | 5 calls, 4 loads, README True | expected 12 | The DocETL amount file had no LLM-derived values for the prose rows, and the values it did extract for prose were wrong ("sub-million" became 1,000,000) |
| usaspending q6 | True | False / False / False | 1 calls, 0 loads, README True | expected 56 | I did not use the DocETL extractions |
| usaspending q7 | True | True / True / True | 2 calls, 1 loads, README True | matched 23 | It parsed the same exact numbers I could read directly |
| usaspending q8 | True | True / True / True | 3 calls, 1 loads, README True | matched 25 | I did not use the DocETL value |
| usaspending q9 | True | False / False / False | 6 calls, 4 loads, README True | expected 147 | I didn't rely on docetl_award_amounts |

## sqlverify

| Question | Acted | Result (cond / base t1 / t2) | Rounds | Condition grader reason |
|---|---|---|---|---|
| GITHUB_REPOS q4 | True | True / True / True | round 1 True -> round 2 True | All repo names matched with fuzzy tolerance. |
| agnews q4 | True | True / True / True | round 1 True -> round 2 True | Ground truth found in LLM output. |
| civic_unstructured q2 | True | False / False / False | round 1 False -> round 2 False | Missing in LLM output: amount '13460000' |
| crmarenapro q13 | False | True / False / False | | Found expected agent ID |
| crmarenapro q4 | False | False / True / True | | No month name found in LLM output |
| imdb q9 | True | True / False / False | round 1 True -> round 2 True | Ground truth found in LLM output. |
| krama q4 | False | True / False / False | | Found expected value: 319655 |
| krama q6 | False | True / False / False | | Found expected value: 3.88 |
| music_brainz_20k q1 | True | True / False / False | round 1 False -> round 2 True | Ground truth found in LLM output. |
| music_brainz_20k q2 | True | True / True / True | round 1 True -> round 2 True | Ground truth found in LLM output. |
| music_brainz_20k q3 | True | True / True / True | round 1 False -> round 2 True | Fuzzy match found ("The earlier answer was wrong ...") |
| stockmarket q1 | True | True / True / True | round 1 True -> round 2 True | Found matching number: 18.44 |
| stockmarket q4 | False | True / False / False | | All names matched |
| yelp q1 | True | True / True / True | round 1 True -> round 2 True | Found matching number: 3.55 |

Warnings sent in the second round and what the agent did are in `docs/METHOD_ANALYSIS.md` section 5.

## Delivered method outputs

- `fdj/civic_unstructured/fdj_funding_project_names.csv`: 99 records, 59 clusters; cluster sizes {1: 37, 2: 8, 3: 11, 4: 2, 5: 1}
- `fdj/music_brainz_20k/fdj_track_duplicates.csv`: 19,375 records, 10,492 clusters; sizes {1: 5825, 2: 2335, 3: 1139, 4: 609, 5: 542, 6: 14, 7: 15, 8: 4, 9: 2, 10: 3, 11: 1, 12: 2}
- `fdj/usaspending/fdj_amounts_to_contracts.csv`: 97,422 pairs, 9,921 left / 9,863 right values; candidates per left {1: 2, 2: 1, 3: 1, 6: 7, 7: 35, 8: 302, 9: 1018, 10: 8555}
- `fdj/usaspending/fdj_documents_to_contracts.csv`: 56,190 pairs, 9,880 left / 9,863 right; candidates per left {1: 3944, 2: 194, 3: 161, 4: 150, 5: 163, 6: 186, 7: 177, 8: 345, 9: 755, 10: 3805}
- `fdj/usaspending/fdj_recipients_to_contracts.csv`: 3,317 pairs, all one-to-one (identity pairs)
- `docetl/DEPS_DEV_V1/docetl_project_metrics.csv`: 770 rows; project_name code 769 / none 1, stars code 769 / llm 1, forks code 770
- `docetl/cve/docetl_cvss_scores.csv`: 68,367 rows, all code
- `docetl/usaspending/docetl_award_amounts.csv`: 10,266 rows; code 681 (of which 159 false values from digit-free prose), none 9,585
- `docetl/usaspending/docetl_recipient_totals.csv`: 3,317 rows, all code; `docetl_agency_totals.csv`: 47 rows, all code
