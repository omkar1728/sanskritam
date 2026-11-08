#!/usr/bin/env bash
# One-time setup on a fresh g4dn.xlarge. From the repo root:
#   export POC_S3=s3://<bucket>/<prefix>          # needs an instance role with s3:GetObject/PutObject/ListBucket
#   export EDGE_S3=s3://<bucket>/EdgeSanskrit-TTS # where you uploaded EdgeSanskrit-TTS/ (not in git; see README.md)
#   bash POC/model_poc/ec2_setup.sh
# Everything lands on the NVMe scratch disk. Re-run after a stop/start: the disk is empty again, so it re-downloads.
set -eu
source POC/model_poc/ec2_env.sh
: "${POC_S3:?set POC_S3=s3://bucket/prefix}"

# 1) EdgeSanskrit-TTS (Vagdhenu + BigVGAN weights and upstream code, ~4.4 GB). Symlinked so backend.app.config finds it.
if [ ! -d "$POC_NVME/EdgeSanskrit-TTS" ]; then
  : "${EDGE_S3:?set EDGE_S3=s3://bucket/EdgeSanskrit-TTS (upload it once from the dev machine)}"
  aws s3 sync "$EDGE_S3" "$POC_NVME/EdgeSanskrit-TTS" --only-show-errors
fi
ln -sfn "$POC_NVME/EdgeSanskrit-TTS" EdgeSanskrit-TTS

# 2) python env on NVMe (CUDA torch per requirements-ec2.txt note: install the CUDA build, not the repo's CPU index)
uv sync
uv pip install -r POC/model_poc/requirements-ec2.txt

# 3) pre-download HF weights into $HF_HOME so run timings exclude download time. IndicF5 may be gated: run `hf auth login` first.
uv run python - <<'PY'
from huggingface_hub import snapshot_download
for r in ("ai4bharat/IndicF5", "ai4bharat/indic-parler-tts"):
    print(r, snapshot_download(r))
PY
# MMS_FA (alignment) downloads on first use into $TORCH_HOME; fetch it now too
uv run python -c "import torchaudio; torchaudio.pipelines.MMS_FA.get_model(with_star=False)"

df -h "$POC_NVME"
