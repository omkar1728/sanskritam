"""Summarise outputs/*/results.json into outputs/summary.md plus a listening sheet (outputs/listen.html).
Runs on any machine, loads no model. Sound quality is NOT judged here: fill the USER-CHECK table by listening."""
import json, sys, html
sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))
import common as K

models = sorted(p.parent.name for p in K.OUT.glob("*/results.json"))
verses = json.loads((K.OUT / "verses_used.json").read_text(encoding="utf-8"))
res = {m: json.loads((K.OUT / m / "results.json").read_text()) for m in models}
L = ["# Model POC summary (timings only; sound quality is a USER-CHECK)", "",
     "| model | verses | mean wall s | mean audio s | mean RTF | peak RAM GB | peak GPU GB |", "|---|---|---|---|---|---|---|"]
for m, r in res.items():
    vs = list(r["verses"].values()); n = len(vs)
    if not n: continue
    avg = lambda k: sum(v[k] for v in vs) / n
    gpu = [v["peak_gpu_gb"] for v in vs if v.get("peak_gpu_gb") is not None]
    L.append(f"| {m} | {n} | {avg('wall_s'):.1f} | {avg('audio_s'):.1f} | {avg('rtf'):.2f} | "
             f"{max(v['peak_rss_gb'] for v in vs):.1f} | {max(gpu):.1f} |" if gpu else
             f"| {m} | {n} | {avg('wall_s'):.1f} | {avg('audio_s'):.1f} | {avg('rtf'):.2f} | {max(v['peak_rss_gb'] for v in vs):.1f} | n/a |")
AL = []
for m in models:
    for dev in ("cpu", "cuda"):
        f = K.OUT / m / f"align_{dev}.json"
        if not f.exists(): continue
        d = json.loads(f.read_text()); vs = list(d["verses"].values())
        if not vs: continue
        n = len(vs); ok = sum(v["ok"] for v in vs)
        t = [v["wall_s"] for v in vs]; rt = [v["rtf"] for v in vs if v["rtf"]]
        AL.append(f"| {m} | {dev} | {d['load_s']} | {sum(t)/n:.2f} | {max(t):.2f} | {sum(rt)/max(len(rt),1):.3f} | "
                  f"{max(v['peak_rss_gb'] for v in vs):.1f} | {ok}/{n} |")
if AL:
    L += ["", "## Alignment (MMS_FA, backend.engine.align)", "",
          "| wav from | device | model load s | mean align s | max align s | mean RTF | peak RAM GB | passed validate() |",
          "|---|---|---|---|---|---|---|---|"] + AL
    L += ["", "Failures list their problems in outputs/<model>/align_<device>.json. Whether highlights match audible words is a USER-CHECK."]
L += ["", "RTF = wall seconds per audio second. The first verse of each model includes load/warm-up cost.", ""]
(K.OUT / "summary.md").write_text("\n".join(L), encoding="utf-8")

rows = []
for v in verses:
    cells = "".join(f'<td><audio controls preload="none" src="{m}/{v["id"]}.wav"></audio></td>' for m in models)
    rows.append(f'<tr><td>{v["id"]}<br>{html.escape(" / ".join(v["padas"]))}</td>{cells}</tr>')
head = "".join(f"<th>{m}</th>" for m in models)
(K.OUT / "listen.html").write_text(
    f'<meta charset="utf-8"><title>Model POC</title><table border="1" cellpadding="6"><tr><th>verse</th>{head}</tr>{"".join(rows)}</table>',
    encoding="utf-8")
print("\n".join(L)); print("wrote", K.OUT / "summary.md", "and", K.OUT / "listen.html")
