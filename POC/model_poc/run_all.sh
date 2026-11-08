#!/usr/bin/env bash
# Run the three POCs one after another (never in parallel: one model process at a time), then alignment, then compare.
# Resumable. Everything runs on the NVMe scratch disk; only the .wav files are synced to $POC_S3/audio after every stage (timings/logs stay on the NVMe).
# From the repo root on EC2:  source POC/model_poc/ec2_env.sh && bash POC/model_poc/run_all.sh
set -u
source POC/model_poc/ec2_env.sh || exit 1
: "${POC_S3:?set POC_S3=s3://bucket/prefix}"
export PYTHONPATH="$PWD"
push() { aws s3 sync "$POC_OUT" "$POC_S3/audio" --exclude "*" --include "*.wav" --only-show-errors || echo "S3 sync FAILED (wavs stay on NVMe)"; }   # audio only
for s in run_vagdhenu run_indicf5 run_parler; do
  echo "=== $s ==="; uv run python POC/model_poc/$s.py 2>&1 | tee -a "$POC_OUT/$s.log" || echo "$s FAILED (continuing)"
  push
done
echo "=== run_align ==="; uv run python POC/model_poc/run_align.py 2>&1 | tee -a "$POC_OUT/run_align.log" || echo "run_align FAILED (continuing)"
uv run python POC/model_poc/compare.py
push
echo "audio in $POC_S3/audio. Timings/summary: $POC_OUT/summary.md (copy it off the box before stopping it)"
