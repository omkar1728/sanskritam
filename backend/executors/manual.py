"""Manual Colab flow: user downloads a bundle zip, runs it in Colab, uploads the result zip."""
import json, shutil, time
from pathlib import Path
from .base import Executor, Cancelled
from .bundle import make_bundle, zip_dir, unzip_safe

class ManualExecutor(Executor):
    name = "colab_manual"
    label = "Colab (manual upload)"
    description = "Download a job bundle, run it in a Colab notebook, upload the result zip. No Drive needed."
    poll_s = 1.0

    def health(self):
        return {"ok": True, "detail": "always available; you move the files by hand"}

    def run(self, spec, workdir, on_progress, is_cancelled):
        from backend.app import db
        wd = Path(workdir); wd.mkdir(parents=True, exist_ok=True)
        timeout = float(db.get_settings().get("colab_manual_timeout_s", 24 * 3600))
        make_bundle(spec, wd / "bundle")
        zip_dir(wd / "bundle", wd / "bundle.zip.part"); (wd / "bundle.zip.part").replace(wd / "bundle.zip")
        on_progress(-1, "Bundle ready: download it, run in Colab, upload the result zip")
        up = wd / "result_upload.zip"
        t0 = time.time()
        while not up.exists():
            if is_cancelled(): raise Cancelled()
            if time.time() - t0 > timeout:
                raise RuntimeError("timed out waiting for the result zip upload")
            time.sleep(self.poll_s)
        unzip_safe(up, wd / "result_tmp")
        src = wd / "result_tmp" / "result"
        shutil.copyfile(src / "chant.wav", wd / "chant.wav")
        info = json.loads((src / "result.json").read_text(encoding="utf-8"))
        shutil.rmtree(wd / "result", ignore_errors=True)
        shutil.move(str(src), wd / "result")
        shutil.rmtree(wd / "result_tmp", ignore_errors=True)
        return dict(info, wav=str(wd / "chant.wav"))
