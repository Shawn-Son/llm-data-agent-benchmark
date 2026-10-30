# DataAgentBench: one-model reproduction

Current run: **gpt-5.6-terra, 104 original questions, 17 datasets, one independent trial per question**. The sweep is running on Great Lakes as Slurm job **65052253**. Verification and archival run in the same allocation after all questions are scored. Partial results are not a completed benchmark score.

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
# After all questions finish:
strict/.venv/bin/python finalize104.py
```

Existing results are retained. Do not rerun scored questions to improve accuracy. Preserve and review interrupted/infrastructure attempts before resuming; an official wrong answer is a valid result.

## Results and evidence

Each question retains prompt, manifest, full CLI events, stderr, extracted commands, work products, answer, grader output and client sessions. Authentication files are removed; final archive is scanned for the key. These are CLI-exposed events, not all hidden model reasoning.

- Runs: `/home/minhyeok/dab-artifacts/terra-native-104x1/runs`.
- Reports: `/home/minhyeok/dab-artifacts/terra-native-104x1/reports`.
- Archive after complete coverage: `/home/minhyeok/dab-archives/terra-native-104x1.tar.gz`.
- Small reports will be committed under `results/terra-native-104x1/`.

The archive keeps one representative auto-downloaded plugin cache and each session’s revision markers, while avoiding repeated cache copies. Agent-deleted intermediate scripts remain in session patch events. Archive includes full trajectories, original tasks/validators, source, installed versions, data provenance and per-file checksums. Original databases remain in the pinned checkout; symlinks do not duplicate them. Restore data against original-data-manifest.json when moving the archive.

No unverified dollar estimate is reported. Raw token usage is retained; actual Toolkit billing is authoritative. Infrastructure/grader exceptions are separate from wrong answers. Semantic failure diagnoses must cite trace evidence and distinguish hypotheses.
