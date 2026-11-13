# Input format: JobRecord JSONL

One JSON object per line, UTF-8, no comments, no trailing commas. File name `*.jsonl` (or `*.jsonl.zst`).

## Fields

| Field | Required | Type | Meaning |
|---|---|---|---|
| `schema` | yes (default 1) | int | always `1` |
| `verse_id` | yes | string | globally unique and stable, only `[a-z0-9_-]`, e.g. `baala-001-001` |
| `padas` | yes | list of strings | the verse lines, none empty, **no danda marks** (`।` `॥` `\|`; they are stripped if present) |
| `work` | no | string | e.g. `ramayana` |
| `book` | no | string | e.g. `baala` (kanda/parvan key) |
| `chapter` | no | int | sarga/adhyaya number |
| `seq` | no | int | order inside the chapter |
| `text_variant` | no | string | which edition the padas come from, e.g. `critical_smith` |
| `text_fallback` | no | bool | true if not the preferred edition |
| `meter` | no | string | reference clip name; default `anuṣṭubh`; the record value beats the command-line flag |
| `render` | no | object | per-verse overrides: `steps`, `seed`, `voice`, `speed`, `cfg`, `gap`, `gap_halant`, `mp3_kbps` |

Any other field is kept as `extra` and copied to the catalog.

## Minimal example (FIXTURE, real critical text of baala-001-001)

```json
{"schema": 1, "verse_id": "baala-001-001", "padas": ["तपःस्वाध्यायनिरतं तपस्वी वाग्विदां वरम्", "नारदं परिपप्रच्छ वाल्मीकिर्मुनिपुंगवम्"]}
```

## Rules

- `verse_id` is lowercase, stable forever (changing it means a new verse), and unique across the whole work.
- `padas` is a list of lines, one per pada/half-verse, without dandas.
- Never edit, correct or normalise the text. Whatever is in the file is spoken.
- Order lines by book, chapter, seq if you can; the planner sorts by these fields anyway.

## Validate (stdlib only, run on the machine where you made the file)

```
python pipeline/tools/validate_input.py ramayana.jsonl
```

It prints counts, duplicate ids and bad records, and exits 1 on any problem.

## Convert the repo's test_data tree

```
python pipeline/tools/epic_json_to_jsonl.py test_data/ramayan/unified ramayana.jsonl --work ramayana
```

Rule: `critical_smith`, else `vulgate_net`, else `vulgate_in`; the choice is recorded in `text_variant` / `text_fallback`.

## Copy to the EC2 box

```
scp ramayana.jsonl ubuntu@<host>:<repo>/pipeline/input/ramayana.jsonl
```

Then run with `--input pipeline/input/ramayana.jsonl`. (Real corpus files are not committed to git.)

`example_fixture.jsonl` in this folder is a FIXTURE (marked with `"extra_note": "FIXTURE"`).
