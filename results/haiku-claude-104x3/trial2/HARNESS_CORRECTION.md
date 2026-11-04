# Harness correction: local database sockets

On 2026-10-30 UTC, trajectory review revealed that the original native profile's disabled network policy also rejected Unix socket connect calls. Database dumps had loaded correctly, but some agents received EPERM from MongoDB/PostgreSQL access and used direct dump parsing instead.

The initial filesystem and external-network preflight had not tested database connectivity. This was a harness defect, not evidence of a model reasoning failure.

## Preservation and selection rule

Stop the initial sweep. Preserve **every attempted server-backed task**, regardless of correct/incorrect result, under `excluded-attempts/unix-socket-blocked/`. Preserve interrupted attempts as well. Retain only completed file-only tasks: DEPS_DEV_V1 (2), GITHUB_REPOS (4), stockindex query1 (1). The rule uses declared backend type, never answer correctness.

The exact list is `harness-correction.json`. Excluded answers, graders and full trajectories remain in the archive; their recorded token usage remains in `attempt-accounting.json`. They do not contribute to the primary 104-trial score.

## Corrected environment

Use Codex's managed network proxy with no allowed external domains. Permit Unix sockets inside the filesystem-constrained view. Keep the filesystem sandbox and credential/grader restrictions. Confirm an actual Unix echo connection succeeds while a direct external connection is unreachable.

After loading all databases, require an in-sandbox test that queries every PostgreSQL database and MongoDB collection. PostgreSQL's local authentication now permits only the read-only role; the administrative role is rejected. MongoDB rejects an insert with authorization error 13. External IP connection remains blocked.

The corrected smoke test passed for 14 server databases, including 127600 AG News documents, 71501 CVE documents, 1651 Krama documents, 9921 USAspending documents and all other declared databases. Its full output is `database-preflight.json`.

Resume with six independent workers as Slurm job 65052253. Final accuracy uses one valid trial per question; no wrong answer from a valid environment is retried to improve the score. Concurrency and the harness revision are recorded in protocol.json. Final reports must state that the driver is reconstructed, not the authors' exact Codex harness.
