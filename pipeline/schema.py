"""JobRecord schema, validation, defaults and parameter resolution (SPEC 5.1, 8)."""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

ENGINE_VERSION = "1"
SCHEMA_VERSION = 1
VERSE_ID_RE = re.compile(r"[a-z0-9_-]+")
DANDAS = "।॥|"

KNOWN_KEYS = {"schema", "verse_id", "padas", "work", "book", "chapter", "seq",
              "text_variant", "text_fallback", "meter", "render"}
HASH_KEYS = ("steps", "seed", "voice", "vocoder", "speed", "cfg", "gap", "gap_halant", "meter")
PARAM_KEYS = ("steps", "seed", "voice", "vocoder", "speed", "cfg", "gap", "gap_halant", "mp3_kbps", "meter")


@dataclass
class JobRecord:
    verse_id: str
    padas: list
    schema: int = 1
    work: str | None = None
    book: str | None = None
    chapter: int | None = None
    seq: int | None = None
    text_variant: str | None = None
    text_fallback: bool = False
    meter: str | None = None
    render: dict = field(default_factory=dict)
    extra: dict = field(default_factory=dict)

    def text_sha256(self) -> str:
        return hashlib.sha256("\n".join(self.padas).encode("utf-8")).hexdigest()

    def to_dict(self) -> dict:
        d = {"schema": self.schema, "verse_id": self.verse_id, "work": self.work, "book": self.book,
             "chapter": self.chapter, "seq": self.seq, "text_variant": self.text_variant,
             "text_fallback": self.text_fallback, "padas": list(self.padas), "meter": self.meter,
             "render": dict(self.render)}
        d.update(self.extra)
        return d


def clean_pada(s: str) -> str:
    return s.strip().rstrip(DANDAS).strip()


def _opt_int(d: dict, key: str):
    v = d.get(key)
    if v is None:
        return None
    if isinstance(v, bool) or not isinstance(v, (int, str)):
        raise ValueError(f"{key} must be an integer, got {v!r}")
    try:
        return int(v)
    except ValueError:
        raise ValueError(f"{key} must be an integer, got {v!r}")


def parse_record(d: dict) -> JobRecord:
    if not isinstance(d, dict):
        raise ValueError("record must be a JSON object")
    schema = d.get("schema", 1)
    if schema != 1:
        raise ValueError(f"unsupported schema {schema!r} (expected 1)")
    vid = d.get("verse_id")
    if not isinstance(vid, str) or not VERSE_ID_RE.fullmatch(vid):
        raise ValueError(f"verse_id must match [a-z0-9_-]+, got {vid!r}")
    padas = d.get("padas")
    if not isinstance(padas, list) or not padas:
        raise ValueError("padas must be a non-empty list")
    out = []
    for i, p in enumerate(padas):
        if not isinstance(p, str):
            raise ValueError(f"pada {i} is not a string")
        c = clean_pada(p)
        if not c:
            raise ValueError(f"pada {i} is empty")
        out.append(c)
    render = d.get("render") or {}
    if not isinstance(render, dict):
        raise ValueError("render must be an object")
    for k in ("work", "book", "text_variant", "meter"):
        if d.get(k) is not None and not isinstance(d[k], str):
            raise ValueError(f"{k} must be a string")
    return JobRecord(
        schema=1, verse_id=vid, padas=out, work=d.get("work"), book=d.get("book"),
        chapter=_opt_int(d, "chapter"), seq=_opt_int(d, "seq"),
        text_variant=d.get("text_variant"), text_fallback=bool(d.get("text_fallback", False)),
        meter=d.get("meter"), render=dict(render),
        extra={k: v for k, v in d.items() if k not in KNOWN_KEYS})


def _coerce(v: str):
    v = v.strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
        return v[1:-1]
    try:
        return int(v)
    except ValueError:
        pass
    try:
        return float(v)
    except ValueError:
        return v


def load_defaults(path=None) -> dict:
    p = Path(path) if path else Path(__file__).with_name("defaults.yaml")
    out = {}
    for ln in p.read_text(encoding="utf-8").splitlines():
        ln = ln.split(" #", 1)[0] if not ln.lstrip().startswith("#") else ""
        if not ln.strip():
            continue
        if ":" not in ln:
            raise ValueError(f"{p}: bad line {ln!r}")
        k, v = ln.split(":", 1)
        out[k.strip()] = _coerce(v)
    return out


def effective_params(rec: JobRecord, defaults: dict, cli: dict | None = None) -> dict:
    cli = {k: v for k, v in (cli or {}).items() if v is not None}
    p = {k: defaults.get(k) for k in PARAM_KEYS}
    for src in (rec.render, cli):
        for k in PARAM_KEYS:
            if k in src and src[k] is not None:
                p[k] = src[k]
    if rec.meter is not None:
        p["meter"] = rec.meter
    return p


def params_hash(params: dict) -> str:
    keys = HASH_KEYS + ("mp3_kbps",)
    payload = {k: params.get(k) for k in sorted(keys)}
    payload["engine_version"] = ENGINE_VERSION
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
