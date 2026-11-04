# DataAgentBench: one-model reproduction

## Repeated runs — terra and Haiku (November 2026)

Same 104 questions, descriptions + hints and unchanged original validators. One run is one full 104-question sweep. **Analysis uses two runs per model:** terra = the original single run + new run 1; Haiku = new runs 1 and 2.

| Model | Harness | Correct / scored, per run | Micro accuracy, mean ± SD | Macro Pass@1, mean ± SD | Pass@2 | Unscored |
|---|---|---|---:|---:|---:|---:|
| gpt-5.6-terra | Codex CLI 0.166.0 | original 59/104 · run 1 61/103 | **57.98% ± 1.76** | **64.71% ± 2.99** | 65.05% (103 q) | 1 |
| claude-haiku-5-5 | Claude Code 2.1.317 | run 1 66/104 · run 2 63/104 | **62.02% ± 2.04** | **62.23% ± 3.02** | 69.23% (104 q) | 0 |

- Each run's accuracy uses that run's scored questions. The one unscored terra question (`DEPS_DEV_V1 q1`, run 1) hit a transient NFS lock error and is never counted wrong. Pass@2 is the share of questions correct in at least one run, over questions scored in both runs. SDs come from two runs.
- On the 103 questions scored in all four runs: terra 57.3% / 59.2%, Haiku 64.1% / 61.2% (macro: terra 65.5% / 66.8%, Haiku 64.4% / 60.1%). Consistency: terra 53 always right, 36 never, 14 mixed; Haiku 57 always, 32 never, 15 mixed. 21 questions were wrong in all four runs, mostly in cve (6), civic_unstructured (4) and usaspending (4).
- **terra run 2 is excluded from the analysis.** It stopped when the U-M GPT Toolkit key hit its usage limit (HTTP 412): 82 of 104 questions were scored before every later call failed. Its reports are kept in `results/terra-native-104x3/trial2/` as a raw record only. Haiku's third run was cancelled before starting.
- **Not a controlled model comparison.** The harnesses differ (Codex vs Claude Code). Claude Code's sandbox masks `/tmp` per command, so files Haiku wrote there vanished between commands; its default 2-minute Bash timeout also fired often. Neither was corrected. Haiku cost (Claude Code estimate): $3.12 and $4.31.
- Validators affect both directions (official grades unchanged): 11 runs answered correctly but were rejected (10 Haiku, e.g. `cve q5` "1.", `PATENTS q3` matcher bug), and 9 Haiku runs passed with wrong answers because the expected value merely appears in the text (e.g. `krama q7`, `crmarenapro q7`). Details in the failure review below.

- **Full trajectory failure review** of all 61 questions any run got wrong (166 wrong runs): main problems per model, shared problems, per-category sub-issues, validator false negatives (11 runs) and false positives (9, all Haiku). See [results/failure-review/FAILURE_REVIEW.md](results/failure-review/FAILURE_REVIEW.md).

Results: [terra aggregate (original + run 1)](results/terra-native-104x3/aggregate/) · [Haiku aggregate (runs 1–2)](results/haiku-claude-104x3/aggregate/) · per-run reports under `results/terra-native-104x3/trial1/` and `results/haiku-claude-104x3/trialN/`. Run with `native104.py --harness codex|claude --trial N`; combine with `codex104/report.py --trials ... --labels ... --dest ...`.

## Results — 104 questions, one trial each

**gpt-5.6-terra answered 59 of 104 questions correctly across 17 datasets.** All 104 trials completed and were scored by unchanged original validators.

| Model | Correct | Wrong | Unscored | Micro accuracy | Macro Pass@1 |
|---|---:|---:|---:|---:|---:|
| gpt-5.6-terra | 59 / 104 | 45 | 0 | **56.73%** | **62.59%** |

Micro accuracy weights every question equally; macro Pass@1 weights every dataset equally. Original descriptions and hints were provided. **Pass@5 was not measured.** This uses a reconstructed Codex harness, so the result is not a controlled comparison against the paper's model scores.

**[Full results and all 45 failure reviews](results/terra-native-104x1/review45.md)** · [104 per-question results](results/terra-native-104x1/runs.csv) · [Structured failure review](results/terra-native-104x1/review45.json) · [Original execution report](results/terra-native-104x1/report.md)

### Results by dataset

| Dataset | Correct / total | Accuracy |
|---|---:|---:|
| DEPS_DEV_V1 | 1 / 2 | 50.0% |
| GITHUB_REPOS | 3 / 4 | 75.0% |
| PANCANCER_ATLAS | 1 / 3 | 33.3% |
| PATENTS | 2 / 3 | 66.7% |
| agnews | 1 / 4 | 25.0% |
| bookreview | 3 / 3 | 100.0% |
| civic_unstructured | 3 / 10 | 30.0% |
| crmarenapro | 10 / 13 | 76.9% |
| cve | 2 / 10 | 20.0% |
| googlelocal | 4 / 4 | 100.0% |
| imdb | 7 / 10 | 70.0% |
| krama | 4 / 10 | 40.0% |
| music_brainz_20k | 3 / 3 | 100.0% |
| stockindex | 3 / 3 | 100.0% |
| stockmarket | 4 / 5 | 80.0% |
| usaspending | 4 / 10 | 40.0% |
| yelp | 4 / 7 | 57.1% |
| **Total** | **59 / 104** | **56.73%** |

CVE, civic_unstructured, krama and usaspending account for **27 of 45 failures (60%)**. These are small, single-trial dataset results; perfect scores do not establish general reliability. [View dataset chart](results/terra-native-104x1/accuracy.svg).

### Failure analysis

**Review scope:** performance was aggregated for all 104 questions; execution traces were reviewed for all **45 wrong answers**. The 59 correct answers were not individually reviewed in depth. Of the 45 failures, **16 have a directly visible mechanism or discrepancy; 29 still require exact-cause or row-level reconciliation**. This is a retrospective assistant review, not an independent second judge.

| Primary review category | Failed runs | Share of 45 |
|---|---:|---:|
| Extraction and representation | 10 | 22.2% |
| Identifier joins and identity | 10 | 22.2% |
| Cohort and aggregation | 9 | 20.0% |
| Temporal state and status | 9 | 20.0% |
| Semantic classification | 5 | 11.1% |
| Execution and unsupported result | 1 | 2.2% |
| Final-answer rounding | 1 | 2.2% |

Each failed run has one primary review category. **The categories include unresolved hypotheses; their shares are not proven causal rates or repair rates.**

| Actual run | Observed failure | Candidate check |
|---|---|---|
| krama q9 | Tool output: 2.4431451613; requested four-decimal answer: 2.4431; final answer: 2.4432. | Compare the final number with the formatted tool value. |
| PANCANCER_ATLAS q3 | Full clinical cohort (N=1,059) gives 305.12; the final answer uses a restricted cohort (N=762), giving 325.34. | Track cohort changes and justify added restrictions. |
| civic_unstructured q6 | A static disaster-project blacklist replaces eligibility as of each grant; answer 123.003M versus expected 88.615M. | Join each grant to the latest applicable dated status. |

Some cases may involve task/validator ambiguity, including the vote-count sorting in imdb q9. **Official grades remain unchanged. No warning or repair intervention has been tested, so no accuracy improvement is claimed.** See the [full case-by-case review](results/terra-native-104x1/review45.md#appendix-all-45-failed-runs) for evidence, uncertainty and proposed checks.

### Usage and completion

- **34,994,764 input tokens** (14,814,739 cached), **558,239 output tokens**, **1,226 tool calls**. Dollar billing was not verified.
- Great Lakes Slurm job **65052253** completed the sweep and verification. Earlier infrastructure attempts were excluded under the [documented correction rule](HARNESS_CORRECTION.md).
- The verified archive preserves all 104 valid trajectories plus excluded harness attempts. [Archive record](results/terra-native-104x1/ARCHIVE.json).
- Regenerate the failure-review Markdown, HTML and CSV with `python3 results/terra-native-104x1/build_review45.py`.

## Protocol and provenance

- Original source: https://github.com/ucbepic/DataAgentBench
- Paper: https://arxiv.org/abs/2603.20576
- Pinned commit: `61fb21e0766d775acae443f6074f5d498e95f938`.
- Exact original query text, database description and hints go to a fresh Codex session. Original query-specific `validate.py` files grade final answers unchanged.
- Descriptions + hints, one trial per question. **Pass@5 is unavailable**. Report question-weighted accuracy and equal-dataset macro Pass@1.
- Native Codex CLI **0.166.0**, U-M GPT Toolkit Responses gateway, **gpt-5.6-terra**, six concurrent tasks, 90-minute maximum per task.
- This is a **reconstructed Codex harness**, not the authors' exact driver/system prompt/tool timeouts. Do not combine scores with older 54-question versions.

## Execution environment

Native bubblewrap preflight passed: Python imports, task writes, data reads, blocked grader/credential reads, unchanged host sentinel and blocked outbound tool network. Inference runs outside the tool sandbox through the gateway. PostgreSQL/MongoDB use Singularity images, job-local Unix sockets and read-only users. All 17 datasets were loaded; data hashes and sizes are recorded.

A local-socket defect in the initial sweep was corrected and all attempted server-backed tasks were excluded regardless of score. See [HARNESS_CORRECTION.md](HARNESS_CORRECTION.md) for the exact rule and tests. Earlier nested Singularity/Codex sandbox attempts failed before the sweep. Diagnostics remain on Great Lakes. **native104.py is the entry point**; container entry points in codex104/run.py and preflight.py are historical. The native runner imports helper functions from them.

## Files and execution

| File | Purpose |
|---|---|
| native104.py | Sandbox preflight, databases, independent sessions, official grading |
| codex104/run.py | Original task/prompt assembly, grader adapter, trajectory metrics |
| codex104/report.py | Coverage checks, tables, HTML report and SVG chart |
| dabbench/data.py, core.py | Original data download/check and provenance manifest |
| finalize104.py | Exact coverage verification, metrics, evidence, credential scan and archive |
| requirements.txt | Dependency constraints; archive records installed versions |

Deployment: `/home/minhyeok/llm-data-agent-benchmark`, upstream `/home/minhyeok/dab-reproduction`, Python 3.12.1 in `strict/.venv`. Adapt explicit paths and Slurm account for another user. Images: runtime/postgres17.sif, runtime/mongo8.sif. Standalone CLI: ~/.local/bin/codex. Keep gateway key outside Git at ~/.config/dab/key, mode 600.

```bash
module load python/3.12.1 singularity
strict/.venv/bin/python native104.py --submit
# --submit also runs finalization after the sweep.
# To regenerate reports/archive without inference:
strict/.venv/bin/python finalize104.py
```

Existing results are retained. Do not rerun scored questions to improve accuracy. Preserve and review interrupted/infrastructure attempts before resuming; an official wrong answer is a valid result.

## Results and evidence

Each question retains prompt, manifest, full CLI events, stderr, extracted commands, work products, answer, grader output and client sessions. Authentication files are removed; final archive is scanned for the key. These are CLI-exposed events, not all hidden model reasoning.

- Runs: `/home/minhyeok/dab-artifacts/terra-native-104x1/runs`.
- Reports: `/home/minhyeok/dab-artifacts/terra-native-104x1/reports`.
- Verified archive: `/home/minhyeok/dab-archives/terra-native-104x1.tar.gz`.
- Final reports and provenance: [`results/terra-native-104x1/`](results/terra-native-104x1/).

The archive keeps one representative auto-downloaded plugin cache and each session’s revision markers, while avoiding repeated cache copies. Agent-deleted intermediate scripts remain in session patch events. Archive includes full trajectories, original tasks/validators, source, installed versions, data provenance and per-file checksums. Original databases remain in the pinned checkout; symlinks do not duplicate them. Restore data against original-data-manifest.json when moving the archive.

No unverified dollar estimate is reported. Raw token usage is retained; actual Toolkit billing is authoritative. Infrastructure/grader exceptions are separate from wrong answers. Semantic failure diagnoses must cite trace evidence and distinguish hypotheses.
