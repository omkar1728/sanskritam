#!/usr/bin/env bash
# Step-size benchmark runner. From the repo root, after the setup in vagdhenu_stepsize.md:
#   source POC/model_poc/ec2_env.sh && bash POC/model_poc/run_steps.sh
# Uploads ONLY the .wav files to $POC_S3/audio/vagdhenu_steps/ . Results/summary stay on the instance-store disk (scp them off).
set -eu
source POC/model_poc/ec2_env.sh
: "${POC_S3:?set POC_S3=s3://bucket/prefix}"
export PYTHONPATH="$PWD" POC_DEVICE=cuda
uv run python -c "import torch,sys; sys.exit(0 if torch.cuda.is_available() else 'CUDA torch missing (repo pins CPU torch)')"
uv run python POC/model_poc/run_vagdhenu_steps.py "$@" 2>&1 | tee "$POC_OUT/vagdhenu_steps.log"
uv run python POC/model_poc/summarize_steps.py
aws s3 sync "$POC_OUT/vagdhenu_steps" "$POC_S3/audio/vagdhenu_steps" --exclude "*" --include "*.wav" --only-show-errors
echo "audio: $POC_S3/audio/vagdhenu_steps/   summary: $POC_OUT/vagdhenu_steps/summary.md"
