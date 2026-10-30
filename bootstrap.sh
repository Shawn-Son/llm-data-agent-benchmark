#!/bin/bash
set -euo pipefail
# Run inside a Slurm allocation, not on the login node.
: "${SLURM_JOB_ID:?Allocate a compute node first}"
command -v apptainer >/dev/null || module load singularity
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
mkdir -p runtime/python-deps
if [ ! -f runtime/python312.sif ]; then
  apptainer pull runtime/python312.sif docker://python:3.12-slim
fi
apptainer exec --bind "$PWD/runtime/python-deps:/deps" --bind "$PWD/requirements.txt:/requirements.txt:ro" runtime/python312.sif python -m pip install --target /deps -r /requirements.txt
.venv/bin/pip freeze > runtime/host-environment.lock.txt
apptainer exec --bind "$PWD/runtime/python-deps:/deps:ro" --env PYTHONPATH=/deps runtime/python312.sif python -m pip list --path /deps --format=freeze > runtime/container-environment.lock.txt
sha256sum runtime/python312.sif > runtime/image.sha256
