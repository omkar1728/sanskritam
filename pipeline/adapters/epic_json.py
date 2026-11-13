"""Repo test_data adapter: <root>/<kanda>/sarga_NNN/verse_NNN.json (SPEC 5.2, D8/D23)."""
from __future__ import annotations

import json
import re
from pathlib import Path

from ..schema import parse_record

VARIANTS = ("critical_smith", "vulgate_net", "vulgate_in")  # never vulgate_gitapress (D23)
KANDA_ORDER = ["baala", "ayodhya", "aranya", "kishkindha", "sundara", "yuddha", "uttara"]
_SARGA = re.compile(r"sarga_(\d+)$")
_VERSE = re.compile(r"verse_(\d+)\.json$")


def pick_variant(text: dict, preferred: str = "critical_smith"):
    """Return (variant, lines, fallback) or (None, None, False). Preferred first, then the D23 fallbacks."""
    order = [preferred] + [v for v in VARIANTS if v != preferred]
    for v in order:
        lines = ((text or {}).get(v) or {}).get("lines")
        if lines and any(isinstance(x, str) and x.strip() for x in lines):
            return v, lines, v != preferred
    return None, None, False


def _kanda_dirs(root: Path) -> list:
    dirs = [p for p in root.iterdir() if p.is_dir()]
    rank = {n: i for i, n in enumerate(KANDA_ORDER)}
    return sorted(dirs, key=lambda p: (rank.get(p.name, len(rank)), p.name))


def iter_records(root, on_invalid=None, on_skip=None, work: str = "ramayana"):
    root = Path(root)
    for kd in _kanda_dirs(root):
        for sd in sorted(p for p in kd.iterdir() if p.is_dir() and _SARGA.match(p.name)):
            for vf in sorted(p for p in sd.iterdir() if _VERSE.match(p.name)):
                try:
                    d = json.loads(vf.read_text(encoding="utf-8"))
                except ValueError as e:
                    if on_invalid:
                        on_invalid(str(root), str(vf), f"bad json: {e}")
                    continue
                if not isinstance(d, dict) or "text" not in d:
                    if on_skip:
                        on_skip(str(root), str(vf))
                    continue
                vid = d.get("id") or ""
                variant, lines, fb = pick_variant(d["text"])
                if variant is None:
                    if on_invalid:
                        on_invalid(str(root), vid or str(vf), "no_text")
                    continue
                try:
                    yield parse_record({
                        "verse_id": vid, "work": work, "book": kd.name,
                        "chapter": d.get("sarga", int(_SARGA.match(sd.name).group(1))),
                        "seq": d.get("seq_in_sarga"), "text_variant": variant, "text_fallback": fb,
                        "padas": list(lines)})
                except ValueError as e:
                    if on_invalid:
                        on_invalid(str(root), vid or str(vf), str(e))
