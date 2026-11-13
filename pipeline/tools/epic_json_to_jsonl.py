#!/usr/bin/env python3
"""Convert the unified test_data tree to JobRecord JSONL (stdlib only, standalone).

usage: python epic_json_to_jsonl.py <root> <out.jsonl> [--work ramayana]
<root> contains <kanda>/sarga_NNN/verse_NNN.json. Text rule: critical_smith, else vulgate_net, else vulgate_in
(fallback is recorded in text_variant / text_fallback). Files without a 'text' key are skipped; verses with no
usable text are listed on stderr and not written.
"""
import argparse
import json
import re
import sys
from pathlib import Path

VARIANTS = ("critical_smith", "vulgate_net", "vulgate_in")
KANDA_ORDER = ["baala", "ayodhya", "aranya", "kishkindha", "sundara", "yuddha", "uttara"]
DANDAS = "।॥|"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("root")
    ap.add_argument("out")
    ap.add_argument("--work", default="ramayana")
    a = ap.parse_args()
    root = Path(a.root)
    rank = {n: i for i, n in enumerate(KANDA_ORDER)}
    kandas = sorted((p for p in root.iterdir() if p.is_dir()), key=lambda p: (rank.get(p.name, 99), p.name))
    written = skipped = notext = fallback = 0
    with open(a.out, "w", encoding="utf-8") as out:
        for kd in kandas:
            for sd in sorted(p for p in kd.iterdir() if p.is_dir() and re.match(r"sarga_\d+$", p.name)):
                for vf in sorted(sd.glob("verse_*.json")):
                    d = json.loads(vf.read_text(encoding="utf-8"))
                    if "text" not in d:
                        skipped += 1
                        continue
                    for v in VARIANTS:
                        lines = (d["text"].get(v) or {}).get("lines")
                        padas = [l.strip().rstrip(DANDAS).strip() for l in (lines or [])]
                        if padas and all(padas):
                            break
                    else:
                        notext += 1
                        print(f"no_text: {d.get('id')} ({vf})", file=sys.stderr)
                        continue
                    rec = {"schema": 1, "verse_id": d["id"], "work": a.work, "book": kd.name,
                           "chapter": d.get("sarga"), "seq": d.get("seq_in_sarga"),
                           "text_variant": v, "text_fallback": v != "critical_smith", "padas": padas}
                    fallback += rec["text_fallback"]
                    out.write(json.dumps(rec, ensure_ascii=False) + "\n")
                    written += 1
    print(f"written: {written}  skipped (no text key): {skipped}  no_text: {notext}  fallback: {fallback}")
    return 1 if notext else 0


if __name__ == "__main__":
    sys.exit(main())
