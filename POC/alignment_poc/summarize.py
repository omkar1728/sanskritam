"""Turn a run_alignment_cost.py result JSON into a markdown table (stdlib only).
    python POC/alignment_poc/summarize.py POC/alignment_poc/results/<run>.json > POC/alignment_poc/alignment_cost.md
"""
import json, statistics as st, sys


def main(path: str):
    d = json.load(open(path, encoding="utf-8"))
    print(f"# Alignment + MP3 cost ({d['run']})\n")
    print(f"Inputs: {d['n_inputs']} WAVs, cores {d['cores']}, free RAM at start {d['free_ram_gb_at_start']} GB.\n")
    print("## Alignment per verse\n")
    print("| mode | model load s | mean s | p95 s | max s | peak RSS MB | ok / total | soft count notes |")
    print("|---|---|---|---|---|---|---|---|")
    for m in d["modes"]:
        if "skipped" in m:
            print(f"| {m['mode']} | skipped: {m['skipped']} | | | | | | |"); continue
        ts = sorted(r["align_s"] for r in m["rows"])
        ok = sum(r["ok"] for r in m["rows"]); soft = sum(1 for r in m["rows"] if r["soft"])
        p95 = ts[min(len(ts) - 1, int(0.95 * len(ts)))]
        print(f"| {m['mode']} | {m['load_s']} | {st.mean(ts):.2f} | {p95:.2f} | {ts[-1]:.2f} | {m['peak_rss_mb']:.0f} | {ok}/{len(ts)} | {soft} |")
    print("\nFailures (first 10 per mode):\n")
    for m in d["modes"]:
        bad = [r for r in m.get("rows", []) if not r["ok"]][:10]
        for r in bad:
            print(f"- {m['mode']} {r['id']} r{r['repeat']}: {r['error']}")
    print("\n## MP3 encode\n\n| kbps | mean s | max s | mean bytes |\n|---|---|---|---|")
    for k, v in (d.get("mp3") or {}).items():
        print(f"| {k} | {v['mean_s']} | {v['max_s']} | {v['mean_bytes']} |")
    if d.get("contention"):
        print("\n## Contention (K parallel post processes)\n")
        print("| processes | threads each | device | wall s | verses | verses/s | mean s/verse | max RSS MB |\n|---|---|---|---|---|---|---|---|")
        for c in d["contention"]:
            if "skipped" in c:
                print(f"| {c['processes']} | | | | | | | {c['skipped']} |"); continue
            print(f"| {c['processes']} | {c['threads_each']} | {c['device']} | {c['wall_s']} | {c['verses']} | {c['verses_per_s']} | {c['mean_per_verse_s']} | {c['max_rss_mb']:.0f} |")
    print("\n## Decision rule (SPEC section 12)\n")
    print("Render on a T4 at 10 steps takes ~7.07 s/verse. If one CPU post worker (cpu1 or cpu4 mean + MP3 mean) is <= 7 s per verse,\n"
          "g4dn.xlarge is enough. Otherwise: 2 post workers, g4dn.2xlarge, or `--align-device cuda`.\n"
          "To see whether post work slows rendering, run this script's contention test while `python -m pipeline bench` renders (manual, EC2 only).")


if __name__ == "__main__":
    main(sys.argv[1])
