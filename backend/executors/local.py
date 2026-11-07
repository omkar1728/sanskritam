import json, os, subprocess, sys
from pathlib import Path
from backend.app import config as C
from .base import Executor, Cancelled

class LocalExecutor(Executor):
    name = "local"

    def health(self):
        ok = (C.MODELS / "vocab.txt").exists() and C.BANK_JSON.exists()
        return {"ok": ok, "detail": "models and bank found" if ok else "models or reference bank missing"}

    def run(self, spec, workdir, on_progress, is_cancelled):
        wd = Path(workdir); wd.mkdir(parents=True, exist_ok=True)
        sp, rp = wd / "spec.json", wd / "result.json"
        sp.write_text(json.dumps(spec, ensure_ascii=False), encoding="utf-8")
        env = dict(os.environ, PYTHONPATH=str(C.ROOT), PYTHONUNBUFFERED="1")
        proc = subprocess.Popen([sys.executable, "-m", "backend.worker.run", str(sp), str(rp)],
                                cwd=C.ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        tail = []
        for line in proc.stdout:
            line = line.rstrip()
            tail = (tail + [line])[-40:]
            if line.startswith("PROGRESS "):
                _, d, n, *msg = line.split(" ", 3)
                on_progress(int(d) / max(int(n), 1), " ".join(msg))
            elif line:
                on_progress(-1, line)
            if is_cancelled():
                proc.kill(); proc.wait(); raise Cancelled()
        if proc.wait() != 0 or not rp.exists():
            raise RuntimeError("worker failed:\n" + "\n".join(tail[-15:]))
        return json.loads(rp.read_text())

from .drive import DriveExecutor
from .manual import ManualExecutor
from .staged import BatchExecutor, StagedExecutor
REGISTRY = {"local": LocalExecutor, "colab_drive": DriveExecutor, "colab_manual": ManualExecutor,
            "colab_batch": BatchExecutor, "colab_staged": StagedExecutor}

def get_executor(name: str):
    if name not in REGISTRY:
        raise ValueError(f"executor '{name}' is not implemented yet (available: {', '.join(REGISTRY)})")
    return REGISTRY[name]()
