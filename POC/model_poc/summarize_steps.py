"""Turn $POC_OUT/vagdhenu_steps/results.json into a per-step markdown table (mean over repeats). Loads no model."""
import json, sys
sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))
import common as K
d = json.loads((K.OUT / "vagdhenu_steps" / "results.json").read_text())
by = {}
for r in d["runs"]: by.setdefault(r["steps"], []).append(r)
m = lambda rs, k: sum(r[k] for r in rs if r[k] is not None) / max(1, len([r for r in rs if r[k] is not None]))
L = [f"GPU {d['meta']['gpu']}, torch {d['meta']['torch']}, verse {d['meta']['verse']}, seed {d['meta']['seed']}, "
     f"{d['meta']['repeats']} repeats (mean; wall min-max in brackets). Warm-up incl. model load: {d['meta'].get('warmup_incl_load_s')} s.", "",
     "| steps | wall s | (min-max) | audio s | RTF | VRAM alloc GB | VRAM reserved GB | RSS GB | GPU util % mean/max | proc CPU % mean | sys CPU % mean |",
     "|---|---|---|---|---|---|---|---|---|---|---|"]
for st in sorted(by):
    rs = by[st]; w = [r["wall_s"] for r in rs]
    L.append(f"| {st} | {m(rs,'wall_s'):.2f} | {min(w):.2f}-{max(w):.2f} | {m(rs,'audio_s'):.2f} | {m(rs,'rtf'):.2f} | "
             f"{max(r['vram_alloc_peak_gb'] for r in rs):.2f} | {max(r['vram_reserved_peak_gb'] for r in rs):.2f} | "
             f"{max(r['rss_peak_gb'] for r in rs):.2f} | {m(rs,'gpu_util_mean'):.0f}/{max(r['gpu_util_max'] or 0 for r in rs):.0f} | "
             f"{m(rs,'proc_cpu_mean'):.0f} | {m(rs,'sys_cpu_mean'):.0f} |")
L += ["", "Proc CPU is % of one core (4 vCPU = 400 max). VRAM columns are per-run peaks (max over repeats)."]
(K.OUT / "vagdhenu_steps" / "summary.md").write_text("\n".join(L), encoding="utf-8"); print("\n".join(L))
