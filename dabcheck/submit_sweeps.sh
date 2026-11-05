#!/bin/bash
# Submit the six method sweeps (3 methods x trials 1-2) as one dependency chain on Great Lakes.
#   bash dabcheck/submit_sweeps.sh <docetl-prep-jobid> <fdj-prep-jobid>
# sqlverify needs no preprocessing and starts first; docetl / fdj trial 1 wait for their preprocessing
# job, and every trial 2 waits for its trial 1 (afterany: a failed trial 1 does not block trial 2).
set -euo pipefail
DOCETL_PREP=${1:?docetl preprocessing job id}; FDJ_PREP=${2:?fdj preprocessing job id}
cd /home/minhyeok/llm-data-agent-benchmark
PY=strict/.venv/bin/python
sub() { $PY native104.py --submit --harness claude "$@" | awk '/^SUBMITTED/{print $3}'; }
S1=$(sub --trial 1 --method sqlverify);             S2=$(sub --trial 2 --method sqlverify --after "$S1")
D1=$(sub --trial 1 --method docetl --after "$DOCETL_PREP"); D2=$(sub --trial 2 --method docetl --after "$D1")
F1=$(sub --trial 1 --method fdj --after "$FDJ_PREP");       F2=$(sub --trial 2 --method fdj --after "$F1")
echo "sqlverify: $S1 $S2   docetl: $D1 $D2   fdj: $F1 $F2"
