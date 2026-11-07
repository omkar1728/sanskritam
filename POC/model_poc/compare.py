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
