"""Input adapters. `iter_records(args, on_invalid=None, on_skip=None)` yields JobRecords from every source given.

on_invalid(source, line_or_id, message) is called for bad records (runner writes failed.jsonl); iteration continues.
on_skip(source, path) is called for epic-json files without a `text` key (not verses).
"""
from __future__ import annotations

from typing import Iterator

from ..schema import JobRecord


def iter_records(args, on_invalid=None, on_skip=None) -> Iterator[JobRecord]:
    g = lambda n: getattr(args, n, None)
    if g("input"):
        from . import jsonl
        yield from jsonl.iter_records(g("input"), on_invalid)
    if g("input_txt"):
        from . import txt
        yield from txt.iter_records(g("input_txt"), on_invalid)
    if g("pg_dsn"):
        from . import postgres
        yield from postgres.iter_records(g("pg_dsn"), table=g("pg_table"), variant=g("pg_variant"),
                                         query=g("pg_query"), on_invalid=on_invalid)
    if g("input_epic_json"):
        from . import epic_json
        yield from epic_json.iter_records(g("input_epic_json"), on_invalid, on_skip)
