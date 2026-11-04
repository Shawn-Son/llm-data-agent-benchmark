# cve identifier join with FDJ (offline, oracle labels)

KEV rows 1583; vulns rows 75199; oracle recomputes 1583/1583 KEV keys exactly; 321 KEV entries have a vulns record; q3 answer from the oracle = 1262 (ground truth 1262).

Plain CVE pattern alone links 10 KEV keys to some vulns key (3 correctly).

FDJ (T=0.9, delta=0.1) on L=1583 x R=2000 (3166000 pairs, 321 true):
- decomposition: (digit_stream_edit <= 12 OR family_decoders <= 0)
- adjusted recall target T' = 1.000, sample recall 1.000
- recall 0.991, precision 1.000, matches 318; recall target feasible on the sample: True
- oracle (L_p) calls: 2060 labels + 3084433 refinement = 3086493 vs 3166000 for the naive all-pairs join
- construction log: [{'step': 'sample', 'note': '60 positives supplied by candidates_fn (uniform sample too sparse)'}, {'step': 'conjunct', 'feature': 2, 'cost': 0.7619047619047619}, {'step': 'disjunct', 'feature': 1, 'clause': 0, 'cost': 0.5573770491803278}]

Join audit (match counts by rule): raw=0, plain_cve=3, family_decoders=10
