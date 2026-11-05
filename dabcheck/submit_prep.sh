#!/bin/bash
# Submit the dataset-level preprocessing of one method condition as a Slurm job on Great Lakes.
#   bash dabcheck/submit_prep.sh docetl 6 4      # method, run budget USD, per-spec budget USD
#   bash dabcheck/submit_prep.sh fdj 9 1.5
#   bash dabcheck/submit_prep.sh docetl 3 3 --dataset usaspending --spec award_amounts   # extra args go to dabcheck.prep
set -euo pipefail
METHOD=${1:?method: fdj or docetl}; BUDGET=${2:?run budget USD}; SPEC=${3:?per-spec budget USD}; shift 3; EXTRA="$*"
PROJECT=/home/minhyeok/llm-data-agent-benchmark
SCRATCH=${DAB_SCRATCH:-/scratch/cse584f26_class_root/cse584f26_class/minhyeok}
mkdir -p "$PROJECT/slurm" "$PROJECT/strict-status" "$SCRATCH/dab-prep"
SCRIPT="$PROJECT/slurm/dabprep-$METHOD.sbatch"
cat > "$SCRIPT" <<EOF
#!/bin/bash
#SBATCH --job-name=dabprep-$METHOD
#SBATCH --account=cse584f26_class
#SBATCH --partition=standard
#SBATCH --cpus-per-task=4
#SBATCH --mem=24G
#SBATCH --time=08:00:00
#SBATCH --output=$PROJECT/strict-status/dabprep-$METHOD-%j.log
set -euo pipefail
module load python/3.12.1
cd $PROJECT
strict/.venv/bin/python -u -m dabcheck.prep --method $METHOD --out $SCRATCH/dab-prep --budget $BUDGET --spec-budget $SPEC $EXTRA
EOF
sbatch --parsable "$SCRIPT"
