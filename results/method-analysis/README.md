# Method-condition analysis (Haiku, November 5, 2026)

| File | What it holds | Produced by |
|---|---|---|
| `../../docs/METHOD_RESULTS.md` | Headline numbers, where each method acted, short per-method findings | written from the tables below |
| `../../docs/METHOD_ANALYSIS.md` | Full analysis: noise floor, per-question evidence, delivered outputs, verifier warnings, limits, next experiments | written from the tables below |
| `../method-comparison/COMPARISON.md` | Accuracy, fixed/lost questions, review-category table, sqlverify verdicts, acted vs untouched | `experiments/compare_methods.py` |
| `STATS.md`, `stats.json` | Wilson intervals, exact McNemar tests, noise floor, five-run pass counts, per-dataset table, effort | `experiments/stats_methods.py` |
| `TRACES.md` | Per-question trajectory evidence: use of method outputs, grader reasons, what the answer says | `experiments/analyze_method_traces.py` (Great Lakes) |
| `RECURRENCE.md` | Whether wrong answers repeat across the five runs; reading of the 22 never-right questions | `experiments/answer_recurrence.py` (Great Lakes) |
| `../haiku-claude-<method>-104x3/trial1/` | Per-question method fields, metrics, per-dataset results, archive record; `verify_summary.json` for sqlverify | `finalize104.py`, `experiments/collect_method_results.py` |
| `../method-prep/<method>/summary.json` | Preprocessing statuses, sizes, costs | `experiments/collect_method_results.py` |

The scripts marked Great Lakes read the full trajectories and answers, which are not in the repository; they live
in the run archives on scratch (paths and checksums in each `ARCHIVE.json`).
