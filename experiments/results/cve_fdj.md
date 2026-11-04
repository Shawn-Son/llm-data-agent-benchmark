# cve identifier join with FDJ (offline, oracle labels)

KEV rows 1583; vulns rows 75199; oracle recomputes 1583/1583 KEV keys exactly; 321 KEV entries have a vulns record; q3 answer from the oracle = 1262 (ground truth 1262).

Plain CVE pattern alone links 10 KEV keys to some vulns key (3 correctly).

FDJ (T=0.9, delta=0.1) on L=1583 x R=2000 (3166000 pairs, 321 true):
- decomposition: (digit_stream_edit <= 16)
- adjusted recall target T' = 0.950, sample recall 1.000
- recall 0.988, precision 1.000, matches 317; recall target feasible on the sample: True
- oracle (L_p) calls: 1320 labels + 3136440 refinement = 3137760 vs 3166000 for the naive all-pairs join

Join audit (match counts by rule): raw=0, plain_cve=4, family_decoders=11
