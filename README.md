# LLM Data Agent Benchmark

Reproduce DataAgentBench workloads with Codex and U-M GPT Toolkit on Great Lakes; preserve data provenance, execution traces, official grading, and reports for team analysis.

**Status: implementation and offline tests completed; live model experiments have not started.** Container preflight, U-M model discovery, database loading, and paid pilot execution must pass before a full sweep. No experimental accuracy is claimed.

## Provenance and reproduction boundary

- Paper: https://arxiv.org/abs/2603.20576 (v3, 104 questions / 17 datasets).
- Original repository: https://github.com/ucbepic/DataAgentBench
- Pinned upstream commit: `61fb21e0766d775acae443f6074f5d498e95f938`.
- Original question text, descriptions, hints, database assets, and `validate.py` graders are reused.
- The public default branch provides a custom ReAct agent. A paper-identical Codex driver was not found among the 27 public branch tips inspected. **Our Codex CLI driver and its generic instruction text are a reimplementation, not the authors' exact Codex harness.** Keep this distinction in any report.
- Changes: U-M gateway, selected model, CLI 0.166.0 initially installed, Apptainer isolation, Linux/Slurm environment, and a per-trial wall-time limit. No claim of identical original tool-call timeouts or system prompt.
- Results on this pinned version must not be silently mixed with older 54-question leaderboard scores.

## Files

| Path | Purpose |
|---|---|
| `dabbench/data.py` | Verify/download upstream assets; stage only sanctioned file databases |
| `dabbench/models.py` | Record gateway-advertised IDs without inference |
| `dabbench/run.py` | Fresh Codex session per question/trial; logs, provenance, grading |
| `dabbench/services.py` | Job-local PostgreSQL/MongoDB startup and original dump loading |
| `dabbench/preflight.py` | No-model check of container imports, filesystem isolation, shell network blocking |
| `dabbench/report.py` | CSV tables, Markdown, standalone HTML and SVG chart, failure-review worksheet |
| `dabbench/archive.py` | Artifact archive with per-file SHA-256 manifest |
| `slurm/pilot.sbatch` | CPU-only pilot job |
| `configs/pilot.json` | One question / one model; execution disabled until preflight passes |

## Great Lakes setup

Existing source checkout: `/home/minhyeok/dab-reproduction`. A new teammate should run:

```bash
GIT_LFS_SKIP_SMUDGE=1 git clone https://github.com/ucbepic/DataAgentBench.git upstream
git -C upstream checkout 61fb21e0766d775acae443f6074f5d498e95f938
salloc -A YOUR_SLURM_ACCOUNT -p standard -c 4 --mem=16G -t 02:00:00
bash bootstrap.sh
source .venv/bin/activate
python -m dabbench.data --upstream upstream --datasets stockindex --download
```

Install Codex according to the official U-M Linux guide. Keep each member's key outside Git, at `~/.config/dab/key` with mode 600. Do not share keys. The budget observed on the owner's Toolkit page was $100/month; this is not a price quote or an experiment spending target.

```bash
python -m dabbench.models --out artifacts/models.json
```

If `/models` is unavailable, inspect the Codex model menu. An advertised model is not necessarily available through Codex: confirm using a bounded pilot. Only `gpt-5.6-terra` was documented by the U-M setup guide; other names must not be guessed.

Edit paths in `configs/pilot.json`; `codex_binary` must resolve to a native standalone executable (not an npm JS launcher). Run:

```bash
python -m dabbench.preflight --config configs/pilot.json
python -m dabbench.run --config configs/pilot.json   # plan only; no model calls
sbatch slurm/pilot.sbatch                          # paid execution, after announcement
```

For server-backed datasets, start services in the **same allocation** before inference:

```bash
python -m dabbench.services --upstream /home/minhyeok/dab-reproduction --runtime runtime --datasets bookreview
```

The Mongo configuration currently assumes local port 27017 is free. Check actual service logs and database connection availability before using Mongo datasets. PostgreSQL uses a job-local Unix socket and read-only role. Mongo query writes are prohibited by instructions but a server-side read-only user remains a deployment hardening item. Both are **unverified on Great Lakes** until the service smoke tests run.

The preflight intentionally fails closed if the Codex sandbox cannot initialize under Apptainer; do not disable it to obtain scores. File-isolation and network controls require validation on the actual cluster. `preflight_passed` must come from the check, not be manually enabled.

## Experiment protocol

1. Verify pinned data and hashes before inference. Save the full `data-manifest.json`.
2. Run one question with one model to measure compatibility, logs, and usage.
3. Select a fixed pilot query set; compare available models on **identical** questions, hints, effort, and time limits.
4. Full coverage is 104 questions × 5 independent trials per model per condition. Test descriptions+hints first; ablations are separate conditions.
5. Save a separate config for every model/condition. Do not resume model sessions between questions. Existing trial directories are never overwritten. Partial/failed trial directories require explicit review.
6. `max_runs` bounds new runs in each invocation. Unknown prices permit only one inference run. Configure verified rates to estimate cost; an estimate is not a hard billing cap. Record actual Toolkit billing separately. Do not launch a full sweep on a $100 allowance without measuring the pilot first.

## Saved artifacts

Each model/condition/dataset/question/trial directory contains:
- `manifest.json`: upstream commit, model, configuration, prompt hash, container/binary hashes, Slurm job, host, timestamps and status.
- `prompt.txt`: exact task prompt.
- `events.jsonl`: complete Codex CLI JSON event stream, including commands and tool results exposed by the CLI.
- `stderr.log`, `commands.json`, `work/`: execution details and intermediate programs/results.
- `work/answer.txt`, `grading.json`, `result.json`: final answer, official grader decision, metrics.
- `agent-home/`: session files; credential file is removed after execution.

CLI events do not expose the model's complete hidden reasoning or necessarily every underlying HTTP request. Missing cost is `null`, never zero. Automatic runtime-error labels are not semantic error analysis.

```bash
python -m dabbench.report --runs /home/minhyeok/dab-artifacts/runs --out /home/minhyeok/dab-artifacts/reports
python -m dabbench.archive --artifacts /home/minhyeok/dab-artifacts --out /home/minhyeok/dab-archives/experiment.tar.gz
```

Reports: `runs.csv`, `queries.csv`, `datasets.csv`, `models.csv`, `summary.json`, `report.md`, `report.html`, `accuracy.svg`, `failure_review.csv`. Open HTML locally, without a server. Inspect failed trajectories and fill failure mode, evidence and reviewer fields; do not treat regex guesses as human-verified failure causes.

Pass@k uses `1 - C(n-c,k)/C(n,k)`. Average within each question, then dataset, then across datasets. Pass@5 is unavailable when fewer than five trials were run. Grader exceptions are recorded separately, not called wrong model answers. Partial coverage reports are labeled as partial; compare only matched datasets/questions.

## Team storage and GitHub

Target repository: **Shawn-Son/llm-data-agent-benchmark**, private (creation/upload pending browser sign-in).

Commit code, configs without secrets, documentation, small reviewed summary tables and figures. Keep the large data and full traces in durable team-accessible storage; preserve archive checksums and retrieval locations in an experiment record. Great Lakes `/scratch` is temporary and is not the sole archive. This project does not automatically publish data, invite collaborators, or upload traces to third-party viewers.

The original repository remains a separate pinned checkout to avoid embedding its large databases or historical results. Respect each original dataset's redistribution terms. The MIT licensing statement in the paper does not replace checking individual source-data licenses.

## Tests

```bash
python -m unittest discover -s tests -v
```

Tests use temporary synthetic events solely to verify arithmetic, tuple-valued graders, escaping, and report generation. They are not benchmark experiments and are never reported as model scores.
