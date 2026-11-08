#!/usr/bin/env bash
# Run the three POCs one after another (never in parallel: one model process at a time). Resumable.
# From the repo root on EC2:  bash POC/model_poc/run_all.sh
set -u
export PYTHONPATH="$PWD"
for s in run_vagdhenu run_indicf5 run_parler; do
  echo "=== $s ==="; python POC/model_poc/$s.py 2>&1 | tee -a POC/model_poc/outputs_${s}.log || echo "$s FAILED (continuing)"
done
echo "=== run_align ==="; python POC/model_poc/run_align.py 2>&1 | tee -a POC/model_poc/outputs_run_align.log || echo "run_align FAILED (continuing)"
python POC/model_poc/compare.py
