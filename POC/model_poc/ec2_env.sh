# Source me (do not execute):  source POC/model_poc/ec2_env.sh
# g4dn.xlarge: the 125 GB NVMe is EPHEMERAL instance store (lost on stop/terminate, kept on reboot). We use it for everything
# heavy (caches, venv, weights, outputs); results are pushed to S3. Required: export POC_S3=s3://<bucket>/<prefix>
NV="${POC_NVME:-}"
if [ -z "$NV" ]; then
  if [ -d /opt/dlami/nvme ] && mountpoint -q /opt/dlami/nvme; then NV=/opt/dlami/nvme      # Deep Learning AMI mounts it here
  else NV=/mnt/nvme; fi
fi
if ! mountpoint -q "$NV"; then
  # not mounted: find the unmounted, unpartitioned NVMe instance-store disk (not the root EBS disk) and format it
  dev=$(lsblk -dpno NAME,MODEL | awk '/Instance Storage/{print $1; exit}')
  [ -n "$dev" ] || { echo "no instance-store NVMe found; set POC_NVME to a writable dir"; return 1; }
  sudo mkfs.ext4 -q -F "$dev" && sudo mkdir -p "$NV" && sudo mount "$dev" "$NV" || return 1
fi
sudo chown "$USER" "$NV" 2>/dev/null
export POC_NVME="$NV"
export HF_HOME="$NV/hf" TORCH_HOME="$NV/torch" UV_CACHE_DIR="$NV/uv-cache" PIP_CACHE_DIR="$NV/pip-cache" TMPDIR="$NV/tmp"
export UV_PROJECT_ENVIRONMENT="$NV/venv" POC_OUT="$NV/outputs"
export XDG_CACHE_HOME="$NV/cache"
mkdir -p "$HF_HOME" "$TORCH_HOME" "$UV_CACHE_DIR" "$PIP_CACHE_DIR" "$TMPDIR" "$POC_OUT" "$XDG_CACHE_HOME"
echo "NVMe scratch: $NV  ($(df -h --output=avail "$NV" | tail -1 | tr -d ' ') free)   outputs: $POC_OUT   S3: ${POC_S3:-<unset>}"
