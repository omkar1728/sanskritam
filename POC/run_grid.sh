#!/usr/bin/env bash
# Each row: name  voice-weights  ref-meter  nfe  sec_per_syll(-1 = clip's own pace)
cd "$(dirname "$0")/.."
M=EdgeSanskrit-TTS/vagdhenu/models
STEER=$M/voice_steer_ema_2026-06-17.pt
ARMA=$M/voice_armA_ema_2026-06-11.pt
mkdir -p POC/outputs/exp
while read -r name voice meter nfe sps; do
  [ -f POC/outputs/exp/$name.wav ] && { echo "skip $name"; continue; }
  echo "=== $name  voice=$(basename ${!voice}) meter=$meter nfe=$nfe sps=$sps"
  /usr/bin/time -f "peak_rss_kb=%M wall=%es" uv run python POC/render_cpu.py \
    --meter "$meter" --padas POC/verse_2_47.json --voice "${!voice}" --voc $M/voc_bigvgan_EMA_2026-06-11.pth \
    --nfe "$nfe" --sec_per_syll "$sps" --out POC/outputs/exp/$name.wav > POC/outputs/exp/$name.log 2>&1
  tail -2 POC/outputs/exp/$name.log
  [ -f POC/outputs/exp/$name.wav ] && ffmpeg -y -loglevel error -i POC/outputs/exp/$name.wav \
    -af "adelay=400,apad=pad_dur=0.3,loudnorm=I=-18:TP=-1.5:LRA=7" -ar 44100 -ac 1 -b:a 192k POC/outputs/exp/$name.mp3
done <<'ROWS'
base_anushtubh_n16 STEER anushtubh 16 -1
vrutta1_n16 STEER vrutta1 16 -1
drutavilambita_n16 STEER drutavilambita 16 -1
shalini_n16 STEER shalini 16 -1
gadya_n16 STEER gadya 16 -1
ROWS
echo GRID_DONE
