"""Selection: filters, shard, skip-done, --only (SPEC 4.1 stage 2, 8)."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Iterable

from .schema import JobRecord, effective_params, params_hash


def parse_chapters(s: str) -> set:
    out = set()
    for part in s.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            a, b = int(a), int(b)
            if a > b:
                raise ValueError(f"bad chapter range {part!r}")
            out.update(range(a, b + 1))
        else:
            out.add(int(part))
    if not out:
        raise ValueError("empty chapter spec")
    return out


def parse_shard(s: str) -> tuple:
    i, k = s.split("/", 1)
    i, k = int(i), int(k)
    if k < 1 or not 0 <= i < k:
        raise ValueError(f"bad shard {s!r}: need 0 <= i < K")
    return i, k


def shard_of(verse_id: str, k: int) -> int:
    return int(hashlib.sha1(verse_id.encode("utf-8")).hexdigest(), 16) % k


@dataclass
class Selection:
    book: list | None = None
    chapters: set | None = None
    ids: set | None = None
    only: str | None = None  # missing | align_failed | failed
    force: bool = False
    shard: tuple | None = None
    limit: int | None = None


@dataclass
class PlannedJob:
    record: JobRecord
    params: dict
    params_hash: str
    reuse: str | None = None


ONLY_VALUES = ("missing", "align_failed", "failed")


def select(records: Iterable, state: dict, sel: Selection, defaults: dict, cli: dict | None = None) -> list:
    if sel.only is not None and sel.only not in ONLY_VALUES:
        raise ValueError(f"--only must be one of {ONLY_VALUES}")
    state = state or {}
    book_order = {}
    kept = []
    for rec in records:
        book_order.setdefault((rec.work or "", rec.book or ""), len(book_order))
        if sel.book is not None and rec.book not in sel.book:
            continue
        if sel.chapters is not None and rec.chapter not in sel.chapters:
            continue
        if sel.ids is not None and rec.verse_id not in sel.ids:
            continue
        if sel.shard is not None and shard_of(rec.verse_id, sel.shard[1]) != sel.shard[0]:
            continue
        kept.append(rec)
    kept.sort(key=lambda r: (r.work or "", book_order[(r.work or "", r.book or "")],
                             r.chapter if r.chapter is not None else 0,
                             r.seq if r.seq is not None else 0))
    jobs = []
    for rec in kept:
        st = state.get(rec.verse_id) or {}
        status = st.get("status")
        params = effective_params(rec, defaults, cli)
        ph = params_hash(params)
        reuse = None
        if sel.only == "missing":
            if st:
                continue
        elif sel.only == "failed":
            if status != "failed":
                continue
        elif sel.only == "align_failed":
            if status != "align_failed":
                continue
            reuse = "wav"
        if (not sel.force and reuse is None and status == "ok"
                and st.get("text_sha256") == rec.text_sha256() and st.get("params_hash") == ph):
            continue
        jobs.append(PlannedJob(rec, params, ph, reuse))
    if sel.limit is not None:
        jobs = jobs[:sel.limit]
    return jobs


def summarize(jobs: list, total_in: int, skipped_done: int) -> dict:
    by_book = {}
    fallback = 0
    for j in jobs:
        key = j.record.book or "?"
        by_book[key] = by_book.get(key, 0) + 1
        fallback += bool(j.record.text_fallback)
    return {"total_in": total_in, "skipped_done": skipped_done, "selected": len(jobs),
            "re_align_only": sum(1 for j in jobs if j.reuse == "wav"),
            "text_fallback": fallback, "by_book": by_book}
