# DEPS_DEV_V1 fork / star extraction (offline)

rows: 770

| extractor | coverage | suspected truncations | warnings |
|---|---:|---:|---|
| naive_forks | 67.0% | 18 | forks: parse coverage 67.0% < 95% (254 of 770 rows unparsed); 18 captures are preceded by digits or commas: the pattern probably truncates numbers with thousands separators |
| forks | 100.0% | 0 | - |
| stars | 99.9% | 0 | - |

| project (q2 ground truth) | true forks | pipeline | naive `(\d+) forks` |
|---|---:|---:|---:|
| mui-org/material-ui | 30522 | 30522 | 522 |
| moment/moment | 7201 | 7201 | None |
| semantic-org/semantic-ui | 4955 | 4955 | 4955 |
| react-native-elements/react-native-elements | 4623 | 4623 | 623 |
| sveltejs/svelte | 4091 | 4091 | 91 |

Unparsed samples (forks pipeline): none
