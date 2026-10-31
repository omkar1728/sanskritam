import subprocess

LEAD_MS = 400     # silence added before the chant in the MP3
TAIL_S = 0.3      # silence added after

def wav_to_mp3(wav: str, mp3: str, lead_ms: int = LEAD_MS):
    """192k mono MP3, loudness-normalised, with a short lead-in/out pad (as in the POC grid)."""
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", wav,
         "-af", f"adelay={lead_ms},apad=pad_dur={TAIL_S},loudnorm=I=-18:TP=-1.5:LRA=7",
         "-ar", "44100", "-ac", "1", "-b:a", "192k", mp3], check=True)
