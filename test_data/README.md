# test_data

Small slice of `sources/ramayan` for tests: Ramayana Bāla kāṇḍa, vulgate sargas 1 to 10 (unified numbering), same directory layout as `sources/ramayan`.

- `ramayan/unified/baala/sarga_001..010` complete verse files; `_report.json` has `per_sarga` and the sarga map filtered, all other fields copied unfiltered from the full run (see its `test_subset` note).
- `ramayan/raw/net/baala/sans1..10.htm`, `raw/in/baala/sarga1..10.html` the matching vulgate pages.
- `ramayan/raw/smith/Ram00.txt`, `Ram01.txt` Smith critical text, whole Bāla file (not cut by sarga; critical sarga N is vulgate N+1 from sarga 8 on).
- `ramayan/raw/gitapress/parsed/` our parse, whole files for Bāla (vol1/vol2 OCR not copied, 39 MB).
- Copyright caveats in `ramayan/README.md` apply (Gita Press). Not added to `.gitignore`; decide before committing.

Use: `uv run python -m backend.app.epics_import --src test_data/ramayan/unified --dry-run` parses and validates without writing (flags confirmed in the module; this run not done). Drop `--dry-run` only against the `sloka_test` database, since the import writes to whatever DB `.env` points at.
