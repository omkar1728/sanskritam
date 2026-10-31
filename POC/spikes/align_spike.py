"""Spike: run MMS_FA alignment on a rendered WAV and print the timing table.
usage: uv run python POC/spikes/align_spike.py <wav>"""
import json, sys
from backend.engine.align import align, validate
PADAS = ["कर्मण्येवाधिकारस्ते मा फलेषु कदाचन", "मा कर्मफलहेतुर्भूर्मा ते सङ्गोऽस्त्वकर्मणि"]
al = align(sys.argv[1], PADAS)
for ln in al["lines"]:
    for w in ln["words"]:
        print(f"{w['slp1']:<16}{w['start']:6.2f}-{w['end']:6.2f}  " + " ".join(f"{s['slp1']}[{s['start']:.2f}-{s['end']:.2f}]" for s in w["syllables"]))
    print()
print("duration", al["audio_duration"], "problems:", validate(al, [16, 16]))
json.dump(al, open(sys.argv[1] + ".align.json", "w"), ensure_ascii=False, indent=1)
