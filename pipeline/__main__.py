"""CLI: python -m pipeline {run,bench,merge,compact,verify,bootstrap} (SPEC section 8).

Every option defaults to None so only flags the user actually gave override pipeline/defaults.yaml.
"""
from __future__ import annotations

import argparse
import sys


def _add_input_flags(p: argparse.ArgumentParser):
    p.add_argument("--input", nargs="+", default=None, help="JSONL file(s) or glob(s)")
    p.add_argument("--input-txt", default=None, help="directory of text files")
    p.add_argument("--pg-dsn", default=None)
    p.add_argument("--pg-query", default=None)
    p.add_argument("--pg-table", default=None)
    p.add_argument("--pg-variant", default=None)
    p.add_argument("--input-epic-json", default=None, help="test_data/ramayan/unified style tree")


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="pipeline", description="Sanskrit chant batch pipeline")
    sub = ap.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="render + align + publish")
    _add_input_flags(r)
    r.add_argument("--dest", default=None)
    r.add_argument("--env", choices=["auto", "aws", "colab", "kaggle", "local"], default=None)
    r.add_argument("--book", default=None, help="comma list, e.g. baala,ayodhya")
    r.add_argument("--chapters", default=None, help="e.g. 1-10 or 1,3,5")
    r.add_argument("--ids", default=None, help="comma list of verse ids")
    r.add_argument("--ids-file", default=None)
    r.add_argument("--only", choices=["missing", "align_failed", "failed"], default=None)
    r.add_argument("--force", action="store_true", default=None)
    r.add_argument("--shard", default=None, help="i/K")
    r.add_argument("--device", choices=["auto", "cuda", "cpu"], default=None)
    r.add_argument("--workers", default=None, help="auto or N render workers per GPU")
    r.add_argument("--steps", type=int, default=None)
    r.add_argument("--seed", type=int, default=None)
    r.add_argument("--meter", default=None)
    r.add_argument("--mp3-kbps", dest="mp3_kbps", type=int, default=None)
    r.add_argument("--limit", type=int, default=None)
    r.add_argument("--keep-wav", action="store_true", default=None)
    r.add_argument("--run-id", default=None)
    r.add_argument("--dry-run", action="store_true", default=None)
    r.add_argument("--fake", action="store_true", default=None, help="fake engine (tests, dry integration)")
    r.add_argument("--align-device", choices=["cpu", "cuda"], default=None)
    r.add_argument("--scratch", default=None)
    r.add_argument("--max-hours", dest="max_hours", type=float, default=None,
                   help="wall-clock budget; on expiry stop cleanly (seal, publish, exit 0)")

    b = sub.add_parser("bench", help="worker-count calibration and align/mp3 timings")
    _add_input_flags(b)
    b.add_argument("--workers", default=None, help="comma list, default 1,2,3")
    b.add_argument("--verses", type=int, default=None, help="verses per process (default 10)")
    b.add_argument("--device", choices=["auto", "cuda", "cpu"], default=None)
    b.add_argument("--steps", type=int, default=None)
    b.add_argument("--seed", type=int, default=None)
    b.add_argument("--meter", default=None)
    b.add_argument("--out-dir", default=None)
    b.add_argument("--align", action="store_true", default=None, help="time align/mp3 on existing WAVs")
    b.add_argument("--wav-dir", default=None)
    b.add_argument("--threads", default=None, help="CPU thread counts for --align, default 1,4")
    b.add_argument("--align-device", choices=["cpu", "cuda"], default=None)
    b.add_argument("--fake", action="store_true", default=None)

    m = sub.add_parser("merge", help="copy segments from other stores, rebuild catalog + manifest")
    m.add_argument("--into", required=True)
    m.add_argument("--from", dest="from_", action="append", default=None)

    c = sub.add_parser("compact", help="live blobs -> final shards")
    c.add_argument("store")
    c.add_argument("--delete-old", action="store_true", default=None)

    v = sub.add_parser("verify", help="check offsets, MP3 headers, JSON, hashes")
    v.add_argument("store")
    v.add_argument("--sample", type=float, default=None, help="fraction of verses to fully check")

    bs = sub.add_parser("bootstrap", help="weights + dependency check")
    bs.add_argument("--target", default=None)
    bs.add_argument("--source", choices=["auto", "s3", "hf"], default=None)
    bs.add_argument("--bucket", default=None)
    return ap


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    if args.cmd == "run":
        from .runner import run
        return run(args)
    if args.cmd == "bench":
        from .bench import bench
        return bench(args)
    if args.cmd == "merge":
        from .merge import merge
        merge(args.into, args.from_ or [])
        return 0
    if args.cmd == "compact":
        from .compact import compact
        compact(args.store, bool(args.delete_old))
        return 0
    if args.cmd == "verify":
        from .verify import verify
        res = verify(args.store, args.sample if args.sample is not None else 0.01)
        if isinstance(res, bool):
            return 0 if res else 1
        if isinstance(res, dict) and "ok" in res:
            return 0 if res["ok"] else 1
        return 0
    if args.cmd == "bootstrap":
        from .bootstrap import bootstrap
        return bootstrap(args)
    return 2


if __name__ == "__main__":
    sys.exit(main())
