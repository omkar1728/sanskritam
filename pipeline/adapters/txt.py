"""Text-dir adapter (SPEC 5.2).

Blocks separated by a blank line. First line `# id: <verse_id> [meter: <name>]`; remaining lines are padas.
Optional header lines before/inside a block: `# work: x`, `# book: y`, `# chapter: n`, `# seq: n`
(a header-only block, i.e. only `# key: value` lines with no id, sets defaults for the following blocks in the file).
If book/chapter/seq are not given they are read from an id like `baala-001-001`.
"""
from __future__ import annotations

import re
from pathlib import Path

from ..schema import parse_record

_ID_RE = re.compile(r"^(?P<book>[a-z0-9_]+)-(?P<ch>\d+)-(?P<seq>\d+)$")
_META = re.compile(r"^#\s*([a-z_]+)\s*:\s*(.*)$")


def _blocks(text: str):
    cur = []
    for ln in text.splitlines():
        if ln.strip():
            cur.append(ln.rstrip())
        elif cur:
            yield cur
            cur = []
    if cur:
        yield cur


def _parse_id_line(rest: str) -> tuple:
    m = re.match(r"^(\S+)(?:\s+meter:\s*(.+))?$", rest.strip())
    if not m:
        raise ValueError(f"bad id line {rest!r}")
    return m.group(1), (m.group(2) or "").strip() or None


def iter_records(root, on_invalid=None):
    root = Path(root)
    files = [root] if root.is_file() else sorted(p for p in root.rglob("*.txt"))
    for f in files:
        defaults = {}
        for bi, block in enumerate(_blocks(f.read_text(encoding="utf-8")), 1):
            where = f"block {bi}"
            try:
                meta, padas = {}, []
                for ln in block:
                    m = _META.match(ln.strip()) if ln.lstrip().startswith("#") else None
                    if m:
                        meta[m.group(1)] = m.group(2).strip()
                    else:
                        padas.append(ln)
                if "id" not in meta:
                    if padas:
                        raise ValueError("block without '# id:' line")
                    defaults.update({k: v for k, v in meta.items()})
                    continue
                vid, meter = _parse_id_line(meta["id"] + (f" meter: {meta['meter']}" if "meter" in meta and "meter:" not in meta["id"] else ""))
                where = f"block {bi} ({vid})"
                d = {"verse_id": vid, "padas": padas, "meter": meter}
                m = _ID_RE.match(vid)
                for key in ("work", "book", "chapter", "seq"):
                    v = meta.get(key, defaults.get(key))
                    if v is None and m and key in ("book", "chapter", "seq"):
                        v = m.group({"book": "book", "chapter": "ch", "seq": "seq"}[key])
                    if v is not None:
                        d[key] = v
                if "text_variant" in meta:
                    d["text_variant"] = meta["text_variant"]
                yield parse_record(d)
            except ValueError as e:
                if on_invalid:
                    on_invalid(str(f), where, str(e))
