"""Colab via a synced/mounted Google Drive folder. The app writes jobs/<id>/ and a Colab worker polls it."""
import json, shutil, time
from datetime import datetime
from pathlib import Path
from .base import Executor, Cancelled
from .bundle import make_bundle

class DriveExecutor(Executor):
    name = "colab_drive"
    label = "Colab (Google Drive folder)"
    description = "Jobs go through a Drive folder synced to this machine; a running Colab notebook picks them up."
    poll_s = 2.0
    sync_check_s = 1.0

    @staticmethod
    def _root():
        from backend.app import db
        d = db.get_settings().get("colab_drive_dir", "").strip()
        return Path(d).expanduser() if d else None

    def health(self):
        root = self._root()
        if root is None: return {"ok": False, "detail": "set 'colab_drive_dir' in Settings"}
        if not root.is_dir(): return {"ok": False, "detail": f"folder does not exist: {root}"}
        try:
            probe = root / ".write_test"; probe.write_text("x"); probe.unlink()
        except OSError as e:
            return {"ok": False, "detail": f"folder not writable: {e}"}
        m = root / "models"
        if not m.is_dir(): return {"ok": False, "detail": "models/ folder missing"}
        missing = []
        if not (m / "vocab.txt").exists(): missing.append("vocab.txt")
        if not list(m.glob("*.pt")): missing.append("voice checkpoint (*.pt)")
        if not list(m.glob("*.pth")): missing.append("vocoder (*.pth)")
        if missing: return {"ok": False, "detail": "models/ is missing: " + ", ".join(missing)}
        return {"ok": True, "detail": f"folder ok: {root}"}

    @staticmethod
    def _status(jd: Path):
        try: return json.loads((jd / "status.json").read_text(encoding="utf-8"))
        except (OSError, ValueError): return None

    def _wait_stable(self, p: Path, is_cancelled):
        last = -1
        while True:
            try: sz = p.stat().st_size
            except OSError: sz = -1
            if sz > 0 and sz == last: return
            last = sz
            if is_cancelled(): raise Cancelled()
            time.sleep(self.sync_check_s)

    def run(self, spec, workdir, on_progress, is_cancelled):
        from backend.app import db
        root = self._root()
        if root is None or not root.is_dir():
            raise RuntimeError("colab_drive_dir is not set or does not exist (Settings)")
        timeout = float(db.get_settings().get("colab_timeout_s") or 3600)
        wd = Path(workdir); wd.mkdir(parents=True, exist_ok=True)
        jd = root / "jobs" / f"{datetime.now():%Y%m%d-%H%M%S}-job{wd.name}"
        make_bundle(spec, jd)
        (jd / "READY").write_text("ready", encoding="utf-8")      # last
        on_progress(-1, f"Job written to {jd.name}; waiting for the Colab worker")
        t0, last = time.time(), None
        while True:
            if is_cancelled():
                (jd / "CANCEL").write_text("cancel", encoding="utf-8"); raise Cancelled()
            st = self._status(jd)
            if st and st != last:
                last = st
                on_progress(float(st.get("progress", -1)) if st.get("state") == "running" else -1, str(st.get("message", st.get("state", ""))))
            if (jd / "FAILED").exists() or (st and st.get("state") == "failed"):
                for _ in range(30):      # FAILED can land before the final status.json is visible (sync lag)
                    if st and st.get("state") == "failed": break
                    time.sleep(0.1); st = self._status(jd)
                raise RuntimeError("Colab worker failed: " + str((st or {}).get("error") or (st or {}).get("message") or "unknown error"))
            if (jd / "DONE").exists():
                break
            if time.time() - t0 > timeout:
                try: (jd / "CANCEL").write_text("timeout", encoding="utf-8")
                except OSError: pass
                raise RuntimeError(f"timed out after {int(timeout)} s waiting for Colab. Is the notebook running "
                                   f"and the worker cell active? Is the Drive folder syncing? (job folder: {jd})")
            time.sleep(self.poll_s)
        src = jd / "result" / "chant.wav"
        self._wait_stable(src, is_cancelled)
        info = {}
        for _ in range(30):
            try: info = json.loads((jd / "result" / "result.json").read_text(encoding="utf-8")); break
            except (OSError, ValueError): time.sleep(self.sync_check_s)
        shutil.copyfile(src, wd / "chant.wav")
        return dict(info, wav=str(wd / "chant.wav"))
