#!/usr/bin/env python3
"""Validate a JobRecord JSONL file (stdlib only, standalone).

usage: python validate_input.py file.jsonl [file2.jsonl ...]
Exit 1 if any record is bad or a verse_id is duplicated.
"""
import json
import re
import sys
from collections import Counter

ID_RE = re.compile(r"[a-z0-9_-]+")
DANDAS = "।॥|"


def check(d):
    if not isinstance(d, dict):
        return "record is not a JSON object"
    if d.get("schema", 1) != 1:
        return f"unsupported schema {d.get('schema')!r}"
    vid = d.get("verse_id")
    if not isinstance(vid, str) or not ID_RE.fullmatch(vid):
        return f"bad verse_id {vid!r} (must match [a-z0-9_-]+)"
    padas = d.get("padas")
    if not isinstance(padas, list) or not padas:
        return "padas must be a non-empty list"
    for i, p in enumerate(padas):
        if not isinstance(p, str) or not p.strip().rstrip(DANDAS).strip():
            return f"pada {i} is empty or not a string"
    for k in ("chapter", "seq"):
        v = d.get(k)
        if v is not None and (isinstance(v, bool) or not isinstance(v, int)):
            return f"{k} must be an integer"
    if d.get("render") is not None and not isinstance(d["render"], dict):
        return "render must be an object"
    return None


def main(argv):
    if not argv:
        print(__doc__)
        return 2
    errors = 0
    total = 0
    ids = Counter()
    by_book = Counter()
    fallback = 0
    for path in argv:
        with open(path, "r", encoding="utf-8") as fh:
            for n, line in enumerate(fh, 1):
                if not line.strip():
                    continue
                total += 1
                try:
                    d = json.loads(line)
                except ValueError as e:
                    print(f"{path}:{n}: invalid JSON: {e}")
                    errors += 1
                    continue
                msg = check(d)
                if msg:
                    print(f"{path}:{n}: {msg}")
                    errors += 1
                    continue
                ids[d["verse_id"]] += 1
                by_book[d.get("book") or "?"] += 1
                fallback += bool(d.get("text_fallback"))
    dups = [k for k, c in ids.items() if c > 1]
    for k in dups[:50]:
        print(f"duplicate verse_id {k} ({ids[k]}x)")
    errors += len(dups)
    print(f"records: {total}  valid: {sum(ids.values())}  unique ids: {len(ids)}  "
          f"duplicates: {len(dups)}  bad: {total - sum(ids.values())}  text_fallback: {fallback}")
    for b, c in sorted(by_book.items()):
        print(f"  {b}: {c}")
    print("OK" if not errors else f"FAILED ({errors} problem(s))")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
