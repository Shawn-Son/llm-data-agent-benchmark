# Failure review instructions (shared by all reviewers)

## Data
- Digests: `/home/claude/analysis/data/digest/<dataset>__query<N>.json`. Each has:
  - `question` (task text), `validator` (the unchanged grading code), `ground_truth` (expected answer data, may be null — then read the expected value from `validator`),
  - `runs`: `T0` = terra original run, `T1` = terra run 1 (both gpt-5.6-terra via Codex CLI), `H1`, `H2` = claude-haiku-5-5 via Claude Code. Each run: `status`, `passed`, `grader_reason`, `answer`, `metrics`, `work_files` (scripts the agent wrote), and `steps` — the ordered trajectory:
    - `msg` (model text shown to the user), `reasoning` (Codex reasoning summary, if any)
    - `cmd` (Codex shell command: `cmd`, `exit`, `out`), `file` (Codex file edit)
    - `tool` (Claude Code tool call: `name`, `input`, `out`, `err`), `denied` (permission refusal), `result` (Claude Code end-of-run)
    - Long outputs are truncated head+tail with a `[N chars cut]` marker.
  - A run that is `null` or has `status` other than `completed` is unscored: ignore it (never treat it as wrong).
- Dataset descriptions and hints: `/home/claude/analysis/data/digest/_datasets.json` (keyed by dataset). The hints describe intentional data corruption (noisy IDs, prose amounts, date conflicts…). Check whether the agent used them.
- You cannot query the databases. Use only what the trajectories print. Do not invent row-level facts; say "unresolved" when the trace does not establish the cause.
- Haiku's hidden thinking is not recorded; judge only from actions and visible text.

## What to do for each assigned question
For every run that is scored and wrong (`passed: false`):
1. Compare the final answer with the expected answer (validator / ground truth). State the exact discrepancy.
2. Walk the trajectory and find the **first divergence**: the earliest step where the agent's plan, filter, join, parse or interpretation departs from what the correct answer requires. Cite the step index (0-based position in `steps`) and a short verbatim excerpt (≤ 200 chars) of the command/output/message that shows it.
3. Assign one **primary category** and one or more **sub-issues** from the taxonomy below (add a new sub-issue code only if none fits; explain it).
4. Record **process signals** seen in that run (codes below).
5. Give an **evidence level**: `supported` (mechanism directly visible in the trace and it explains the discrepancy), `likely` (visible mechanism, but the trace does not prove it fully explains the number), `unresolved`.
6. Write a 2–4 sentence **root-cause narrative**: what exactly went wrong and why, concretely (tables, columns, regexes, filters, dates, counts).
If a question has both a correct and a wrong run for the same model (**mixed**), add `mixed_contrast`: what the correct run did differently (one or two sentences, with step indices).
If both models give the same wrong answer, or the answer looks semantically right but the validator rejects it, say so in `validator_or_task_note`.

## Taxonomy
Primary categories: `Extraction and representation`, `Identifier joins and identity`, `Cohort and aggregation`, `Temporal state and status`, `Semantic classification`, `Answer format vs validator`, `Execution and unsupported result`.

Sub-issues:
- E1 prose/number formats not parsed as the hints describe (e.g. "six-figure", spelled-out amounts) ; E2 regex/pattern coverage gap ; E3 wrong representation or unit vs what is asked (names vs codes, range bounds vs versions) ; E4 manual transcription/copy of IDs or values ; E5 noisy field decoding (dates, booleans, attributes)
- J1 obfuscated/noisy key decoding failure ; J2 entity/name normalization over- or under-merging ; J3 duplicate records not merged ; J4 join cardinality or positional alignment error ; J5 wrong join key or table
- C1 missing or extra filter (cohort) ; C2 aggregate from the wrong source (metadata vs rows) ; C3 ranking/tie/ordering interpretation ; C4 wrong denominator ; C5 stops at first match instead of global answer
- T1 static status instead of as-of-date status ; T2 date parsing or window boundary ; T3 conflicting document dates (stated vs internal) handled wrongly ; T4 wrong event date field (created vs signed etc.)
- S1 keyword-heuristic labels ; S2 policy/rule judgment ; S3 category scope (name-based instead of category field)
- V1 answer right but rejected by validator format ; V2 task or validator ambiguity ; V3 rounding/formatting of the final value
- X1 gave up / reported lower bound or estimate instead of an answer ; X2 tool or runtime failure that changed the outcome

Process signals (codes, list all that apply to the run):
- `tmp_loss` file written to /tmp missing in a later step (Claude Code sandbox) ; `timeout` command timed out ; `error_loop` ≥3 failing commands in a row on the same issue ; `hardcoded` hand-typed lists/IDs/values used in the computation ; `no_hint_use` the relevant hint was ignored ; `no_verification` final number not cross-checked although an obvious check existed ; `hedged` answer framed as estimate/lower bound/low confidence ; `declined` no definite answer ; `sampled` used a sample/LIMIT instead of full data ; `wrong_db` looked in the wrong database/collection.

## Output
Write one JSON file (path given in your task) — a list, one object per question:
```json
{"dataset": "...", "query": "queryN", "expected": "short expected answer",
 "runs": {"T0": {"passed": false, "answer_short": "...", "discrepancy": "...", "first_divergence": {"step": 12, "excerpt": "..."},
                 "primary": "Identifier joins and identity", "sub_issues": ["J1"], "signals": ["hedged"],
                 "evidence": "supported|likely|unresolved", "narrative": "..."},
          "T1": {...}, "H1": {...}, "H2": {...}},
 "mixed_contrast": {"terra": "...", "haiku": "..."},
 "validator_or_task_note": "...",
 "question_summary": "one sentence: the root problem of this question across models"}
```
For a passed run write `{"passed": true}` only. For an unscored run write `{"passed": null}`.
Keep excerpts verbatim and short. Be concrete and conservative. Then reply with a 5-line summary of the most common sub-issues in your group.
