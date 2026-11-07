"""Executors for epic batches rendered in Colab. 'colab_batch' jobs wait for a results.zip (never run);
'colab_staged' jobs have their wav + result.json already staged in <workdir>/staged and just feed the normal
mp3 + alignment + upload pipeline."""
import json, os
from pathlib import Path
from .base import Executor


class BatchExecutor(Executor):
    name = "colab_batch"
    label = "Colab batch"
    description = "Internal: epic batch jobs awaiting a results.zip."
    hidden = True

    def health(self):
        return {"ok": True, "detail": "batch jobs are rendered by the Colab batch notebook"}

    def run(self, spec, workdir, on_progress, is_cancelled):
        raise RuntimeError("colab_batch jobs are not run by the app; upload results.zip to the batch")


class StagedExecutor(Executor):
    name = "colab_staged"
    label = "Colab batch (staged result)"
    description = "Internal: result already uploaded."
    hidden = True

    def health(self):
        return {"ok": True, "detail": "reads files staged by the batch result upload"}

    def run(self, spec, workdir, on_progress, is_cancelled):
        wd = Path(workdir); sd = wd / "staged"
        wav, rj = sd / "chant.wav", sd / "result.json"
        if not wav.exists() or not rj.exists():
            raise RuntimeError("staged result missing (chant.wav / result.json)")
        info = json.loads(rj.read_text(encoding="utf-8"))
        os.replace(wav, wd / "chant.wav")
        on_progress(-1, "Using wav rendered in Colab batch")
        return {"wav": str(wd / "chant.wav"), "duration": info["duration"],
                "pada_spans": info.get("pada_spans", []), "syllables": info.get("syllables", [])}
