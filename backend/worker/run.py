"""Worker entry: `python -m backend.worker.run spec.json result.json`.
Used by the local executor (and later by SSH/notebook executors). Progress goes to stdout as
`PROGRESS <done> <total> <message>` lines."""
import json, sys
from backend.engine.synth import Engine, RenderSpec

def main(spec_path: str, result_path: str):
    spec = RenderSpec(**json.load(open(spec_path, encoding="utf-8")))
    res = Engine().render(spec, lambda d, n, m: print(f"PROGRESS {d} {n} {m}", flush=True))
    json.dump(res, open(result_path, "w"))
    print("DONE", flush=True)

if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
