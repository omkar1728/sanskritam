# Ramayana unified source

One JSON file per verse, built by combining every source we have. `source.md` is the original research handoff; this file is the record of the whole process, including the small details that affect correctness.

## Layout
- `raw/` downloaded originals. Untrusted; never edit.
  - `smith/Ram00.txt` Smith's README; `Ram01.txt` to `Ram07.txt` the seven kāṇḍa files (Baroda Critical Edition, Unicode Devanagari).
  - `net/<kanda>/sans<N>.htm` valmikiramayan.net, one page per vulgate sarga.
  - `in/baala/sarga<N>.html` valmikiramayan.in (only Bāla is published there).
  - `gitapress/vol1.txt`, `vol2.txt` archive.org OCR of the Gita Press Hindi edition; `gitapress/parsed/` our parse of it.
- `scripts/` `fetch_bala.sh`, `fetch_net.sh`, `fetch_all_net.sh` (downloads, 0.4 to 0.5 s between requests), `parse_gitapress.py`, `build_unified.py`.
- `unified/<kanda>/sarga_NNN/verse_NNN.json`, `_sarga.json`, and `unified/<kanda>/_report.json`.

Rebuild a kāṇḍa: `python3 -I scripts/build_unified.py <this dir> <key>` with key in `baala ayodhya aranya kishkindha sundara yuddha uttara`. Run Python with `-I` on downloaded data.

## Sources and what each contributes
| Source | Text | Meanings | Coverage |
|---|---|---|---|
| Smith (bombay.indology.info) | Baroda Critical Edition, Devanagari, no danda marks | none | all 7 kāṇḍas |
| valmikiramayan.net | vulgate Devanagari with danda marks (edition not named) | English word-for-word (ITRANS), English translation, English commentary | kāṇḍas 1 to 6, no Uttara |
| valmikiramayan.in | vulgate Devanagari | Hindi translation, Hindi word table (provenance unstated; table looks machine-generated) | Bāla only |
| Gita Press Hindi edition, archive.org OCR (vol 1 and 2) | OCR Devanagari | Hindi translation | all 7 kāṇḍas |

The Gita Press scans carry a CC0 label set by the uploader; Gita Press may still hold copyright, so confirm before redistributing. Its text is OCR and unverified.
Sites that were examined and not used: enjoylearningsanskrit.com (all rights reserved, translator unnamed), ramcharit.in, advocatetanmoy.com, vedapath.app, sanskritdocuments (Smith-derived, not independent), IIT Kanpur (unreachable from here). The YouTube links in `sources.txt` are not used.

## Process
1. Download raw files into `raw/`.
2. Parse each source (`build_unified.py`): Smith lines by id; net pages by verse anchors (several anchors can share one text block and one translation); `.in` by `shloka-card` blocks.
3. Map critical sargas to vulgate sargas by text, because the two editions number sargas differently (Bāla: critical has 76 sargas, vulgate 77, and from sarga 8 on, critical N is vulgate N+1; the other kāṇḍas differ too). Each mapping is recorded in `_report.json` with how it was found. A mapping that had to be inferred is marked `INFERRED`.
4. Within each sarga, align the sources line by line (a line is a half-verse, two pādas) by text similarity, with the net text as hub. Similarity below 0.60 is never matched; below 0.85 is flagged `LOW`.
5. Group the aligned rows into verse files. A file is anchored on a critical-edition verse; rows that exist only in the vulgate form their own `vulgate_only` file placed after the verse they follow.
6. Attach meanings by source unit. When a unit covers more than one of our verses it is repeated and flagged `spans_beyond_this_verse`.
7. Completeness audit: every line of every source and every meaning unit must appear in some output file. `completeness_ok` in `_report.json` must be true.

## Rules that came from the sources' own READMEs
Smith's README (Ram00.txt) applies to the critical text:
- Line ids are `<kāṇḍa 1 digit><sarga 3><verse 3><pāda letter>`. Letters: `a` and `c` are the two lines of a verse; `e` and `g` are extra lines (longer verses). Each line holds two pādas.
- In longer metres (triṣṭubh and similar) a semicolon marks the pāda division inside a line. We keep the line verbatim and add `pada_split`. Comparison ignores the semicolon.
- Star passages (marked `*`, e.g. 59*) are lines the printed edition says to read but which the electronic text does not insert, because they would break the numbering. They appear only in README's notes section. We parse those notes into `critical_edition_notes` on the verse they follow, verbatim, and never insert them into the text. Notes that cannot be attached are listed under `unattached_notes` in the report.
- The README's list of differences from the printed edition is complete; its errata corrections are already applied (Bāla 1.9.7 to 8, 1.13.22 to 24, 1.15.25 to 27, 1.26.16 to 19 have corrected numbering).
- In Devanagari, forms like किंचित् are single words; अथ वा and periphrastic perfects (कथयां बभूव) are two words. The text is NFC-normalised. Spelling differences between sources (anusvara versus a nasal plus virama, final म् versus ं, spacing, avagraha) are treated as the same text for matching only; each source's own spelling is stored.
- Smith states the text "still contains many errors"; do not treat it as error-free. Two typos were reported in Sundara (5.1.99, 5.1.55); not checked against the printed volumes.

Other details:
- Critical text has no punctuation. `punctuated_derived` adds a danda after the first line and a double danda after the second, only for two-line verses. It is derived, not source text.
- net word meanings are ITRANS; the Devanagari beside them is our own conversion (`devanagari_machine_converted`), unchecked.
- A missing source in a verse is `null`. Nothing is guessed or filled in.
- Every meaning carries its source. Hindi meanings from `.in` and the Gita Press OCR are marked unverified. `review_status` is `unreviewed` everywhere.
- The net site has typos in its locators (a kāṇḍa number that is wrong); these go to `net_locator_anomalies` in the report, not to the data.
- Attribution: Muneo Tokunaga (typing), John D. Smith (standardisation), G. H. Bhatt et al. and the Oriental Institute, Baroda (Critical Edition), K. M. K. Murthy and Desiraju Hanumanta Rao (valmikiramayan.net English), Gita Press (Hindi).

## Verse file fields
`id` (`<kanda>-<sarga>-<seq>`), `kanda`, `sarga`, `seq_in_sarga`, `refs` (critical and vulgate references), `kind` (`critical` or `vulgate_only`), `text` (`critical_smith`, `vulgate_net`, `vulgate_in`), `alignment` (each row with similarity, confidence and word-level differences), `meanings`, `critical_edition_notes`, `flags`, `review_status`.

## Known limits
- Alignment quality is measured by text similarity, not by a reader; `LOW` rows and `INFERRED` sarga mappings need a human look.
- Hindi meanings: Bāla from valmikiramayan.in and Gita Press; kāṇḍas 2 to 7 only from Gita Press OCR.
- Uttara has no English meanings.
