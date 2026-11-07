# Sanskrit study app: handoff for Claude Code

Exported from a Claude cloud session (Oct–Nov 2026) so the work can continue locally in Claude Code. It has two parts:

- **Part A:** sourcing and cross-checking an accurate Devanagari text of the Vālmīki Rāmāyaṇa for the user's internal Sanskrit study app (the most recent work).
- **Part B:** a text-to-audio skill for reading Sanskrit verses aloud, slowly and clearly (an earlier thread; Bhagavad Gītā 2.47 was the test verse).

Read this top section first, then the part you're working on.

## Standing instruction from the user

> Never make assumptions, always ask clarifying questions. Only make assumptions when I state them explicitly. Always use pop ups to clarify these questions

In Claude Code, use the AskUserQuestion tool for clarifications and don't guess.

## General notes for both parts

- The cloud sandbox these were researched in blocked Hugging Face, GitHub and most data hosts (HTTP 403 via proxy). pip worked. Nothing could be downloaded or listened to, so every quality and accuracy claim below is unverified until tested locally.
- Web pages were read through a summarising page reader, so details such as exact spellings or counts can contain transcription errors. Re-check them against the real files.
- Part A and Part B overlap in one place: if the app later reads verses aloud, the text from Part A can feed the audio pipeline of Part B (devanagari in, MP3 out).

## Part A: Vālmīki Rāmāyaṇa source text for the study app

### A1. Goal and decisions made

The user has built an **internal app for studying Sanskrit text**. They want the **most accurate direct text input**: Devanagari, all seven kāṇḍas, copy-pasteable. A PDF was preferred, but any format works ("any works").

Decisions and answers from the user:
- **Script:** Devanagari.
- **Scope:** all seven kāṇḍas (Bāla, Ayodhyā, Araṇya, Kiṣkindhā, Sundara, Yuddha, Uttara).
- **Recension:** "Not sure". My recommendation was the Baroda Critical Edition (the scholarly standard). The traditional Southern/Northern vulgate text is a different text, not interchangeable with it.
- **What the app needs:** verse-level structure (kāṇḍa / sarga / śloka numbering) and proper punctuation (danda ।, double danda ॥). Sandhi-split text and commentary were **not** requested.
- **Licensing:** "anything works".
- **Accuracy check:** both provenance assessment and sample comparison between sources.
- **Next goal:** combine several source texts into **one unified, cross-checked text**. (The user wrote "tests"; I asked and they confirmed they meant "texts".)

### A2. Key learnings

1. **No single clean, complete PDF with copyable Devanagari exists** among the sources found. The best-structured option is a set of seven plain-text Unicode Devanagari files, one per kāṇḍa.
2. **Most digital copies are one text.** Almost everything traces to one typing of the Baroda Critical Edition (G. H. Bhatt et al., Oriental Institute, Baroda, 1960–1975, 7 volumes) by Prof. Muneo Tokunaga (Kyoto, late 1980s–early 1990s), standardised and corrected by Prof. John D. Smith (Cambridge). Agreement between sites that share this lineage is **not independent confirmation**, and errors are copied along with the text.
   - Lineage seen: Tokunaga (1993) → Smith (1995) → TITUS (Gippert, 2008) → Sanskrit Library TEI XML v0.1 (2010); Tokunaga → Smith → ITRANS conversion → Sanskrit Documents Devanagari pages (Unicode Devanagari and PDF versions added Jan 2009); Smith's current files (bombay.indology.info, README updated 25 Sep 2020, the Sundara file header says 25 Sep 2021) → GRETIL "1st revised version". Oliver Hellwig made a separate **"2nd revised version" of kāṇḍas 2 and 3 only**, listed on GRETIL.
3. **The editor admits errors remain.** Smith's page says this text "has not been submitted to rigorous revision and scrutiny" (unlike his electronic Mahābhārata) and "still contains many errors". His README says it is not yet fully accurate and should be used with caution. He gives no error rate and doesn't say which kāṇḍas are more reliable.
4. **Two apparent typos checked in Sundara Kāṇḍa** (read through a web page reader, so transcription isn't guaranteed; re-check by script):
   - 5.1.99: the files read *rāghāvasya* (राघावस्य) where *rāghavasya* (राघवस्य) is expected.
   - 5.1.55 (line `c`): the files read *saṃprakaśete* (short *a*) where *saṃprakāśete* is expected.
   - Both appear in Smith's Devanagari file, Smith's Roman file, and (for 5.1.99) the enjoylearningsanskrit.com copy, which states no source. That site is probably a copy of the same data, not a second witness.
   - These were **not** checked against the printed Baroda volumes or any independent digital text.
5. **A meter check should catch many such typos.** The text is mostly anuṣṭubh (8-syllable quarter-verses), and a wrong vowel length breaks the pattern. Smith's page links meter-analysis tools.
6. **Version notes:** Smith's files are CRLF (convert to LF before using grep). The Roman and ASCII versions are the same text in other encodings.
7. **Tool caveat:** my web page reader truncated the Sundara file at about sarga 7, so the truncation is the reader's, not necessarily the file's. Don't infer file size from what I saw.
8. **The cloud sandbox couldn't download from these hosts** (HTTP 403 via proxy). Everything below was read through a summarising page reader. Test download access on the local machine.

### A3. Source catalogue

Statuses: **Checked** = I read the page; **Not opened** = found in links or search results but not read.

#### A3.1 Smith's critical-edition files (primary candidate): Checked

- Site: https://bombay.indology.info/ramayana/ (welcome page https://bombay.indology.info/ramayana/welcome.html, statement https://bombay.indology.info/ramayana/statement.html)
- Edition: Baroda Critical Edition (1960–75), typed by Tokunaga, converted and standardised by Smith. License: none stated; Tokunaga gave permission for this use.
- Files, one folder per encoding, same eight file names:

| Book | Unicode Devanagari (UD) | Unicode Roman (UR, ISO 15919) | ASCII (Harvard/Kyoto) |
|---|---|---|---|
| 0 README | https://bombay.indology.info/ramayana/text/UD/Ram00.txt | https://bombay.indology.info/ramayana/text/UR/Ram00.txt | https://bombay.indology.info/ramayana/text/ASCII/Ram00.txt |
| 1 Bāla | https://bombay.indology.info/ramayana/text/UD/Ram01.txt | …/UR/Ram01.txt | …/ASCII/Ram01.txt |
| 2 Ayodhyā | https://bombay.indology.info/ramayana/text/UD/Ram02.txt | …/UR/Ram02.txt | …/ASCII/Ram02.txt |
| 3 Araṇya | https://bombay.indology.info/ramayana/text/UD/Ram03.txt | …/UR/Ram03.txt | …/ASCII/Ram03.txt |
| 4 Kiṣkindhā | https://bombay.indology.info/ramayana/text/UD/Ram04.txt | …/UR/Ram04.txt | …/ASCII/Ram04.txt |
| 5 Sundara | https://bombay.indology.info/ramayana/text/UD/Ram05.txt | …/UR/Ram05.txt | …/ASCII/Ram05.txt |
| 6 Yuddha | https://bombay.indology.info/ramayana/text/UD/Ram06.txt | …/UR/Ram06.txt | …/ASCII/Ram06.txt |
| 7 Uttara | https://bombay.indology.info/ramayana/text/UD/Ram07.txt | …/UR/Ram07.txt | …/ASCII/Ram07.txt |

- Structure (observed in the Sundara file only; verify on the others):
  - Header lines start with `%` and give title, last-updated date and encoding.
  - Each text line starts with an ID like `5001001a`: kāṇḍa (1 digit), sarga (3 digits), verse (3 digits), then a letter.
  - Letters seen: `a`, `c`, `e`. Each line is about 16 syllables, so a **half-verse** (two quarter-verses). `e` appears on some verses (possibly extra lines in irregular verses).
  - **No danda or double danda marks.** Verse and sarga boundaries are inferred from the IDs.
- Each of the seven kāṇḍa files has its own "Last updated" date, comparable with the website.
- The README says it documents spelling conventions and differences from the printed edition.

#### A3.2 GRETIL: Checked (index page only; files not opened)

- Index: https://gretil.sub.uni-goettingen.de/gretil.html (Epics → Ramayana)
- "1st revised version" (Smith). Script not specified on the index page.
  - TEI XML: https://gretil.sub.uni-goettingen.de/gretil/corpustei/sa_rAmAyaNa.xml
  - HTML: https://gretil.sub.uni-goettingen.de/gretil/corpustei/transformations/html/sa_rAmAyaNa.htm
  - Plain text: https://gretil.sub.uni-goettingen.de/gretil/corpustei/transformations/plaintext/sa_rAmAyaNa.txt
- "2nd revised version" by Oliver Hellwig, **kāṇḍas 2 and 3 only**:
  - XML: https://gretil.sub.uni-goettingen.de/gretil/corpustei/sa_vAlmIki-rAmAyaNa-rev-2-3.xml
  - HTML: https://gretil.sub.uni-goettingen.de/gretil/corpustei/transformations/html/sa_vAlmIki-rAmAyaNa-rev-2-3.htm
  - Plain text: https://gretil.sub.uni-goettingen.de/gretil/corpustei/transformations/plaintext/sa_vAlmIki-rAmAyaNa-rev-2-3.txt
- A separate "Ramayana, Southern recension" entry (input by Hellwig) has XML/HTML/TXT files at corresponding `gretil.sub.uni-goettingen.de/gretil/corpustei/` paths. The exact file names were not given in what I read.
- No explicit license on the entry. It notes some TITUS downloads are restricted or proprietary.

#### A3.3 The Sanskrit Library (TITUS-derived TEI XML): Checked (metadata pages only)

- Pages: https://sanskritlibrary.org/catalogsText/titus/ram/ram01.html through ram07.html (e.g. https://sanskritlibrary.org/catalogsText/titus/ram/ram05.html)
- Edition: Baroda Critical Edition. Version 0.1 "First XML edition", Providence, RI, 2010. Edited by Peter M. Scharf, markup by Matthias Ahlborn.
- Format: TEI XML. Transliterated Roman text with diacritics. The pages are metadata only and link to TITUS for the text.
- License: **Creative Commons Attribution-NonCommercial-ShareAlike 3.0**.
- No proofreading or accuracy notes.

#### A3.4 Sanskrit Documents Project, Baroda-edition pages: Checked (description pages only)

- https://sanskritdocuments.org/mirrors/ramayana/valmiki/ramayana.htm (form to choose format, kāṇḍa and chapter, with next/previous navigation), https://sanskritdocuments.org/mirrors/ramayana/valmiki/process.htm, https://sanskritdocuments.org/mirrors/ramayana/thanks.htm
- Edition: Baroda Critical Edition (Tokunaga → Smith's CSX version → Perl scripts → ITRANS 5.1 → Devanagari pages with XDVNG fonts and PostScript). **Jan 2009 update: Unicode Devanagari and PDF versions added**, converted from the ITRANS files.
- Likely the closest thing to the "PDF with copyable text" the user first asked for, **but** I could not find the file locations, and it comes from an older conversion path than Smith's current files, so it probably has more errors. One result URL, https://sanskritdocuments.org/mirrors/ramayana/utf/7_uttarakanda_2.html, was blocked from automated reading (robots.txt), so I could not check it.
- No proofreading or accuracy statements.

#### A3.5 Southern-recension sites: Checked unless noted

- **valmikiramayan.net / sanskritdocuments.org/sites/valmikiramayan:** https://valmikiramayan.net/utf8/ramayana.shtml, https://sanskritdocuments.org/sites/valmikiramayan/sundara/sundara_contents.htm
  - English translation (K. M. K. Murthy, Desiraju Hanumanta Rao) with ITRANS/Devanagari/Roman text and word meanings. Verse-per-page URLs such as https://sanskritdocuments.org/sites/valmikiramayan/sundara/sarga1/sundarasans1.htm (Devanagari), `sundaraitrans1.htm`, `sundararoman1.htm`.
  - **Uttara Kāṇḍa is not listed.** Chapter counts: Bāla 77, Ayodhyā 119, Araṇya 75, Kiṣkindhā 67, Sundara 68, Yuddha 128.
  - Edition is not named. No PDF. The Devanagari looked garbled when I read it.
- **IIT Kanpur Vālmīki site (Southern Recension):** http://www.valmiki.iitk.ac.in and https://valmiki.iitk.ac.in/links. Electronic text, English translation, Sanskrit commentaries. **Not opened** (blocked); only its related-links page was read.
- **hindunet.org copy:** http://www.hindunet.org/ramayana/ (via https://ramcharitmanas.iitk.ac.in/node/5). Described as complete, in XDVNG Devanagari, ITRANS and Devanagari PostScript. **Not opened**; no per-kāṇḍa file list seen.

#### A3.6 Digital Corpus of Sanskrit (DCS), sandhi-split: Checked indirectly

- The IIT Kanpur annotation guidelines (https://sanskrit.iitk.ac.in/valmikiramayana/guidelines.pdf) say the Rāmāyaṇa source is the DCS corpus, sandhi-split with morphological and lexical analysis, held as **CoNLL-U** files on GitHub (link not captured).
- A thesis (https://arxiv.org/pdf/2406.18276) reports a corpus of **18,754 verses**. It does not name the edition. The guidelines mention the Dharmalaya edition (Ramayana Sanskrit to Tamil) as a printed reference, which is a Southern-type text.
- Useful for word-level study, not for verbatim text. The source edition needs confirming before use.

#### A3.7 Clay Sanskrit Library (Goldman translation with facing Sanskrit): Checked (excerpt only)

- https://claysanskritlibrary.org/wp-content/uploads/2021/08/CSL_RamayanaBook_V-1.pdf (Book Five, Sundara, excerpt)
- Sanskrit text credited to the Oriental Institute, Baroda; translated by Robert P. Goldman and Sally J. Sutherland Goldman. Sanskrit in **Roman transliteration with diacritics** (not Devanagari). The excerpt's text layer had extraction errors (dropped letters, split words).
- A hand-edited, published text, so potentially a useful **independent check**. Which other volumes exist, and whether they're free, is not confirmed.

#### A3.8 Printed and scanned editions (for ground-truth checks): Not opened beyond listings

- **Printed Baroda Critical Edition:** G. H. Bhatt (general editor) et al., Oriental Institute, Baroda, 1960–1975, 7 volumes. The gold standard for resolving disputes. No scans located.
- Internet Archive: https://archive.org/details/361952998SrimadValmikiRamayanaSanskrit1933AD/page/n45/mode/2up (1933 Sanskrit edition; scan, needs OCR). Several other Internet Archive records appeared in search results; I did not check whether they carry Sanskrit text or only translations.

#### A3.9 Aggregators and derived datasets (avoid as primary text): Checked

| Source | What it is | Concerns |
|---|---|---|
| https://github.com/bhavykhatri/DharmicData | JSON per kāṇḍa (`ValmikiRamayana/1_balakanda.json` … `7_uttarakanda.json`), ODbL-1.0, claims about 24,000 shlokas | Credited to a third-party repo (svenkatreddy/Ramayana_Book), no edition named, no validation. Whether the text is Devanagari wasn't confirmed. |
| https://github.com/imradhe/ramayanam (and https://github.com/imradhe/ramayanam-api) | MIT-licensed JSON in progress (id, kanda, sarga, sloka, text, meaning, translation) | Links back to IIT Kanpur's site, six kāṇḍas listed (no Uttara), completeness unknown. |
| https://huggingface.co/insightpublica/ramayana-indic (IWLV-Ramayana, https://arxiv.org/pdf/2604.13078) | Sarga-aligned parallel corpus; Sanskrit layer from a "critical edition", cross-checked with GRETIL | Sarga-level only, only English and Malayalam layers complete, other layers use AI-assisted translations. |
| https://enjoylearningsanskrit.com/scriptures/ramayana/book-5/chapter-1/verse-99, https://vedapath.app/sa/ramayana/sundara-kanda/1/9 | Per-verse viewers | No source stated; the first reproduces the 5.1.99 variant above. |

### A4. Reported size figures (not reconciled)

These differ by edition and by how chapters and verses are counted. None is a confirmed count for the Baroda Critical Edition.

| Figure | Source |
|---|---|
| 7 kāṇḍas, 493 sargas | IWLV paper (follows Griffith's translation, cross-checked with GRETIL) |
| Bāla 77, Ayodhyā 119, Araṇya 75, Kiṣkindhā 67, Sundara 68, Yuddha 128 (Uttara not listed) | valmikiramayan.net (Southern) |
| Yuddha 131; 537 sargas across six kāṇḍas | imradhe/ramayanam README |
| 18,754 verses | DCS thesis (arXiv 2406.18276) |
| about 24,000 shlokas | DharmicData README |

Compute counts from the downloaded files and compare them with the printed edition's contents before treating any figure as correct.

### A5. Proposed pipeline: one unified, cross-checked text

Principle: **do not majority-vote**. Sources that share a lineage agree because they copy the same typing, so their agreement proves nothing. Weight sources by independence, and settle disputes with the printed edition.

1. **Define the output schema:** `id` (kāṇḍa.sarga.verse.pāda-letter), `devanagari`, `source`, `recension`, `flags` (typo suspected, variant, unresolved), `review_status`.
2. **Base text:** Smith's UD files (A3.1). Normalise to Unicode NFC, convert CRLF to LF, strip the `%` header.
3. **Witnesses, by lineage:**
   - Same lineage, differences show corrections over time: GRETIL 1st revised, Hellwig's 2nd revised (kāṇḍas 2–3, a genuinely revised text), the Sanskrit Library XML (2010), Sanskrit Documents Devanagari/PDF (2009).
   - More independent: Clay Sanskrit Library (hand-edited, Roman), printed-edition scans, and for the Southern recension, IIT Kanpur and GRETIL's Southern entry.
4. **Convert witnesses to one script and one ID scheme,** transliterating Roman to Devanagari where needed, so they can be compared line by line.
5. **Diff and classify** each difference: spelling convention, sandhi convention, real variant reading, probable typo.
6. **Automatic validators:**
   - Meter check (Smith links meter tools): quarter-verse length and light/heavy pattern, to flag wrong vowel lengths.
   - Dictionary and morphology check (e.g. Sanskrit Heritage tools, DCS lexicon) for tokens that aren't valid words, such as *rāghāvasya*.
   - Structural check: gaps in verse numbering, missing letters, sarga counts.
7. **Resolve:** accept a correction only when the printed edition or an independent witness supports it; otherwise queue the line for human review. Keep a versioned corrections file (id, old, new, reason, evidence).
8. **Add punctuation:** a single danda after the first half-verse of each śloka and a double danda at its end, using the `a` / `c` letter structure. Check this against irregular verses (the `e` lines) before applying it everywhere.
9. **Publish** as JSONL or SQLite with provenance on every line. Record the licence/attribution for each source used.

### A6. Open questions (ask with AskUserQuestion; don't assume)

- Final recension: Critical Edition only, or also the Southern/vulgate text for comparison? (Numbering and verse content differ between them.)
- Is Uttara Kāṇḍa required? (Some Southern-recension sites omit it. Scholars widely regard Bāla and Uttara as later additions.)
- Do they have access to the printed Baroda volumes or scans to settle disputes?
- Should the app display variants and corrections, or only the final unified text?
- Attribution wording for Tokunaga, Smith, Hellwig and the Baroda editors.
- Does the app need sandhi-split text after all (e.g. from DCS)?

### A7. Caveats on this research

- No files were downloaded or parsed; I read pages through a summarising reader, so spelling quotes and structure details could contain transcription errors.
- GRETIL's script, the contents of its files, IIT Kanpur's site, the DCS GitHub source, and the Sanskrit Documents PDF locations were **not** verified.
- The counts in A4 are inconsistent across sources, and not confirmed for the Baroda text.
- Only two typo locations were examined, in one kāṇḍa.

### A8. Suggested first prompt for Claude Code (Part A)

> Read this file, Part A. Ask me the open questions in A6 using AskUserQuestion. Then download Smith's seven Devanagari files (A3.1), GRETIL's plain-text files (A3.2) and Hellwig's revision of kāṇḍas 2–3. Normalise and align them by ID, diff them, run a meter check and a dictionary check, and give me a report of flagged lines before you write any unified text. Don't assume anything I haven't said. Tell me what to review by hand.

---

## Part B: Sanskrit text-to-audio skill

### 1. Goal

The user wants audio of Sanskrit text with clear, extremely precise, slow pronunciation. They want to turn this into a reusable **skill** that converts Sanskrit (Devanagari) text to audio, and they plan to build it **locally using Claude Code**. They also want the voice to be much less robotic than the first attempt.

Decisions the user has made:
- Output format: **MP3**
- Language scope for the skill: **Sanskrit only** (shlokas and Devanagari verses)
- Acceptable voice improvements: **free offline neural voice** and **human recordings, slowed down**. A paid cloud TTS API was *not* selected.
- Where the skill will run: **their own computer** (they said "not sure yet" in the questionnaire, then said they will implement it locally with Claude Code).
- Their last explicit request was only for a plan and options, with nothing built yet. The skill has **not** been drafted.

Test text, Bhagavad Gītā 2.47:

```
कर्मण्येवाधिकारस्ते मा फलेषु कदाचन।
मा कर्मफलहेतुर्भूर्मा ते सङ्गोऽस्त्वकर्मणि॥
```

IAST: karmaṇy evādhikāras te mā phaleṣu kadācana / mā karma-phala-hetur bhūr mā te saṅgo 'stv akarmaṇi

### 2. What was built (first attempt, in the cloud sandbox)

Result: a ~14 s, 192 kbps mono MP3 with an even, slow, unstressed delivery. The user judged it **"too robotic"**. It was never listened to by the assistant (no audio playback is available), so pronunciation was only checked by reading back the engine's phoneme trace.

#### Why it sounded robotic and how pronunciation was handled
- The sandbox could install pip packages but **could not reach Hugging Face or GitHub** (HTTP 403 via proxy), and `apt-get install espeak-ng` failed (package not found). So no neural voice model could be downloaded.
- The engine used was **eSpeak NG**, a rule-based formant synthesizer, loaded from the pip package `espeakng-loader` through `ctypes` (`libespeak-ng.so`). That is the main cause of the robotic voice.
- eSpeak NG ships **no Sanskrit voice or dictionary** in the pip bundle (only `hi_dict`, `mr_dict`, `ne_dict` and similar). Passing Devanagari to the `hi` voice applies Hindi rules and produces wrong Sanskrit: it drops final schwas (e.g. *kadācana* → "kadāchan") and changes vowels (e.g. the *-kāraḥ* vowel).
- Workaround: **bypass text-to-phoneme entirely**. Hand-write phonemes in eSpeak's mnemonic notation and pass them as `[[...]]` with the `espeakPHONEMES` flag (0x100) set. Without that flag the engine reads `[[...]]` as English spelling (an early bug).
- The engine's phoneme trace (IPA actually spoken) was checked and matched the intended Sanskrit.

#### Phoneme mapping used (eSpeak mnemonics)
`@` = a (inherent short a, kept everywhere), `a:` = ā, `e:` = ē, `o:` = ō, `u:` = ū, `n.` = ṇ, `s.` = ṣ, `N` = ṅ, `tS` = c (as in "church"), `#` after a consonant = aspiration (dh, ph, bh), `H` = h. The avagraha (ऽ) is silent.

#### Prosody choices
- Voice `hi`, rate 95 wpm, pitch 45, pitch range 30.
- Every vowel was marked with secondary stress (`,`) to flatten the stress accent into an even, syllable-timed delivery. Marking nothing gave a single stress per word; primary stress (`'`) was longer and stronger.
- Pauses: 0.4 s lead-in, 0.55 s after pādas 1 and 3, 0.95 s after pādas 2 and 4, 0.3 s tail.
- Post-processing: ffmpeg `loudnorm=I=-18:TP=-1.5:LRA=7`, resampled to 44.1 kHz mono, `libmp3lame` at 192k.

#### Environment facts
- Python 3.13, ffmpeg available at `/usr/local/bin/ffmpeg`, onnxruntime present.
- `pip install piper-tts` succeeded but was **not used** for synthesis: it only bundles espeak phonemization data (no audio synthesis, no Sanskrit dictionary).
- Run helper scripts normally. `python3 -I` blocked importing my own local helper module.

#### Working code

`synth_lib.py`:

```python
import ctypes, espeakng_loader, array
lib = ctypes.CDLL(espeakng_loader.get_library_path())
libc = ctypes.CDLL(None)
libc.fopen.restype = ctypes.c_void_p
libc.fopen.argtypes = [ctypes.c_char_p, ctypes.c_char_p]
libc.fflush.argtypes = [ctypes.c_void_p]
lib.espeak_Initialize.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_char_p, ctypes.c_int]
lib.espeak_SetVoiceByName.argtypes = [ctypes.c_char_p]
lib.espeak_SetParameter.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_int]
lib.espeak_SetPhonemeTrace.argtypes = [ctypes.c_int, ctypes.c_void_p]
lib.espeak_Synth.argtypes = [ctypes.c_char_p, ctypes.c_size_t, ctypes.c_uint, ctypes.c_int, ctypes.c_uint, ctypes.c_uint, ctypes.c_void_p, ctypes.c_void_p]
CB = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.POINTER(ctypes.c_short), ctypes.c_int, ctypes.c_void_p)
SR = lib.espeak_Initialize(2, 0, espeakng_loader.get_data_path().encode(), 0)  # 2 = synchronous
_samples = array.array("h")
@CB
def _cb(wav, n, ev):
    if wav and n > 0:
        _samples.extend(wav[:n])
    return 0
lib.espeak_SetSynthCallback(_cb)

def setup(voice="hi", rate=105, pitch=45, rng=30, trace=None):
    assert lib.espeak_SetVoiceByName(voice.encode()) == 0
    lib.espeak_SetParameter(1, rate, 0)   # rate wpm
    lib.espeak_SetParameter(3, pitch, 0)  # pitch
    lib.espeak_SetParameter(4, rng, 0)    # pitch range
    lib.espeak_SetParameter(2, 100, 0)    # volume
    if trace:
        f = libc.fopen(trace.encode(), b"w")
        lib.espeak_SetPhonemeTrace(3, f)  # 3 = mnemonics + IPA (original code wrote `1 | 2 << 0 if False else 3`, which is just 3)
        return f

def say(text):
    global _samples
    _samples = array.array("h")
    b = text.encode("utf-8")
    lib.espeak_Synth(b, len(b) + 1, 0, 1, 0, 1 | 0x100, None, None)  # POS_CHARACTER, UTF8 | PHONEMES
    lib.espeak_Synchronize()
    return array.array("h", _samples)
```

`build_verse.py`:

```python
import re, wave, array, synth_lib as S

V = re.compile(r"(a:|e:|o:|i:|u:|@|a|e|i|o|u)")
def mark(s): return V.sub(lambda m: "," + m.group(1), s)

# Bhagavad Gita 2.47, four 8-syllable padas, hand-phonemized for Sanskrit
# (espeak mnemonics: @=a, a:=ā, n.=ṇ, s.=ṣ, N=ṅ, tS=c, #=aspiration)
padas = [
  ("karmaṇyevādhikāraste", "k@rm@n.je:va:d#ika:r@ste:"),
  ("mā phaleṣu kadācana",  "ma: p#@le:s.u k@da:tS@n@"),
  ("mā karmaphalahetur bhūr", "ma: k@rm@p#@l@He:tur b#u:r"),
  ("mā te saṅgo 'stvakarmaṇi", "ma: te: s@Ngo: stv@k@rm@n.i"),
]
f = S.setup(voice="hi", rate=95, pitch=45, rng=30, trace="final_trace.txt")
sr = S.SR
def silence(sec): return array.array("h", [0]) * int(sr * sec)

audio = silence(0.4)
for i, (iast, ph) in enumerate(padas):
    marked = " ".join(mark(w) for w in ph.split())
    clip = S.say("[[" + marked + "]]"); S.libc.fflush(f)
    print(f"pada {i+1}: {iast:28s} {marked:60s} {len(clip)/sr:.2f}s")
    audio.extend(clip)
    audio.extend(silence(0.95 if i % 2 == 1 else 0.55))
audio.extend(silence(0.3))

with wave.open("verse.wav", "wb") as w:
    w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr)
    w.writeframes(audio.tobytes())
print("total", round(len(audio)/sr, 2), "s at", sr, "Hz")
```

MP3 encode:

```bash
ffmpeg -y -i verse.wav -af "loudnorm=I=-18:TP=-1.5:LRA=7" -ar 44100 -ac 1 -codec:a libmp3lame -b:a 192k out.mp3
```

Engine trace that confirmed the intended phonemes (IPA actually spoken):

```
kˌərmˌəɳjˌeːʋˌaːdʰˌikˌaːɾˌəstˈeː
mˌaː pʰˌəlˌeːʂˌu kˌədˌaːtʃˌənˈə
mˌaː kˌərmˌəpʰˌəlˌəhˌeːtˌuɾ bʰˈuːɾ
mˌaː tˌeː sˌəŋɡˌoː stʋˌəkˌərmˌəɳˈi
```

Known weak spot: ह (ha) is voiced lightly (like English /h/) instead of Sanskrit's breathy ɦ.

### 3. Search for pre-recorded slow versions (the user found existing ones too fast)

All findings below are from web pages read in the session. None of the audio was listened to. Pace was not stated on most pages. The assistant could not download audio from the sandbox.

| Resource | What it is | Notes |
|---|---|---|
| Aarsha Vidya Varshini chanting page: https://www.aarshavidyavarshini.org/bgchanting.html | Free, per-chapter MP3s for all 18 chapters, made for "learn by listening and repeating"; each track downloadable, plus a zip link on Google Drive. Chapter 2 is `audio/BGChapter2.mp3`. | One file per chapter, so 2.47 must be cut out. Chanter names are not on the page. Pace not stated. The mailing-list post says chanters are Jaishankar Narayanan and Srividya. |
| Udemy "Guided Easy Gita Chanting for Beginners" (Dr. Anjali Ghanekar): https://www.udemy.com/course/guided-easy-gita-chanting-for-beginners/ | Lead-and-follow chanting with harmonium; page says verses are chanted at a **very slow speed**. Free preview. | Organized by yoga path, so Chapter 2 / verse 47 coverage is unconfirmed. Price not listed. |
| James Boag, Gītā 2.40–2.50 on YogaAnytime: https://yogaanytime.com/class-view/915/video/Yoga-Gita-240-250-Recitation-by-James-Boag | 5-minute call-and-response, about 16 syllables at a time, with a pause for the learner to repeat. | Needs a subscription or a 15-day trial. Not described as slow. |
| Vyoma "Gita karaoke" pronunciation course: https://vyoma.edmingle.com/courses/learn-authentic-pronunciation-of-gita-karaoke-7165 | All 18 chapters, 21 karaoke videos. | $3.16, free preview, pace not stated. |
| Vyoma "Learn to Chant Gita": https://vyoma.edmingle.com/courses/learn-to-chant-gita-7241 | Free; Chapter 2 sessions with Smt. Brunda Karanam. | Pace not stated. |
| Udemy "Gītā Complete Pronunciation Guide": https://www.udemy.com/course/shreemad-bhagavad-gita-complete-pronunciation-guide/ | About 24-minute Chapter 2 lecture; free preview. | Granularity not stated. |
| GitaVani (Android, F-Droid, MIT): https://f-droid.org/packages/com.nikhilsi.gitavani/ | Audio for all 701 verses. | No speed control mentioned. Recording source not stated. |
| Swadhyaya (iPhone): https://apps.apple.com/us/app/id1463711994 | Free; shloka audio with pauses. | No speed control mentioned. |

Pages checked that have **no** audio: shlokam.org (player present but no details), enjoylearningsanskrit.com, vedabase.io, heritage.iitk.ac.in/gitasupersite (the old Gītā Supersite, now Heritage IIT Kanpur), avg-sanskrit.org, sanskritlibrary.org course page.

Idea: take any good recording, cut out the verse, and slow it **without changing pitch** with ffmpeg (`atempo=0.7`, chained for lower values, or use rubberband), so it sounds like the same chanter at a slower pace. Check the recording's usage terms before sharing.

### 4. Neural / free options researched for a better voice

None were tested. The sandbox could not download them. All claims come from the project pages.

| Option | Details | Catches |
|---|---|---|
| **EdgeSanskrit-TTS** (MIT): https://huggingface.co/Hari7718/EdgeSanskrit-TTS | Built on AI4Bharat IndicF5 (flow-matching, about 337M params) with the Vocos vocoder, 24 kHz. Weights bundled in the repo (about 1.5 GB, needs Git LFS). Runs **offline on CPU**; the author reports about 0.8× real time on one CPU thread for one Gītā verse. Its phonemizer maps Devanagari to phonetic symbols, **keeps the inherent short "a"**, and applies sandhi rules for visarga and anusvara. Text is routed through **Kannada script** for IndicF5. Voice, pitch and rhythm come from **reference recordings of a Sanskrit chanter**. | Depends on a pinned IndicF5 commit. The English-to-Sanskrit translation feature needs an OpenRouter API key (not needed for Devanagari input). Speed claim rests on one benchmark. Output quality depends on the reference audio. |
| **Vāgdhenu** (Apache-2.0): https://github.com/sharadcodes/vagdhenu | Meter (vṛtta) aware shloka-to-**chant** TTS on IndicF5/F5-TTS with a fine-tuned BigVGAN-v2 vocoder. Single-speaker pārāyaṇa style, durations shaped by meter. Routes Sanskrit through Kannada script to avoid Hindi schwa deletion. Pretrained weights and a Gradio demo are on Hugging Face. README cites about 4.6 MOS from expert listeners. | Needs Python 3.10 and a **CUDA 12.1 GPU**. Single speaker. Setup downloads weights. A paper (arXiv 2608.26146) exists but could not be read (PDF had no extractable text). |
| **Indic Parler-TTS** (Apache-2.0): https://huggingface.co/ai4bharat/indic-parler-tts | Officially supports Sanskrit, with recommended speaker "Aryan". Speaking rate (slow to fast), expressivity and "very clear audio" are set through a text description. About 0.9B params; uses a GPU if present, otherwise CPU. | Files require accepting access conditions on Hugging Face. The model page itself recommends a newer model, "Indic-Speak". Sanskrit pronunciation caveats are not documented. |

Other things surfaced in searches but **not investigated**: `snorbyte/snorTTS-Indic-v0`, `rverma0631/Sanskrit_TTS` on Hugging Face, `ai4bharat/vits_rasa_13`, `pronoobie/piper-voices-hindi` (Hindi Piper voices only; Piper has no Sanskrit voice), Sarvam (a cloud API), the Respair NeMo pronunciation-customization notebook.

Key technical pitfall to carry forward: **Hindi-style schwa deletion** produces wrong Sanskrit. Both Vāgdhenu and EdgeSanskrit-TTS avoid it by routing Devanagari through **Kannada script** (which keeps the inherent "a" explicit). A skill should keep that step whichever engine it uses.

### 5. Recommended skill design (proposed, not yet built)

1. **Input handling:** accept Devanagari text, split into pādas (at spaces and punctuation, and at | / ॥ danda marks), handle the avagraha (ऽ, silent) and keep a small overrides file for words that sound wrong.
2. **Engine choice, in order:**
   - Default: **EdgeSanskrit-TTS** (offline, CPU-capable).
   - If a CUDA GPU is available: **Vāgdhenu** for meter-aware chanting.
   - Pace control through **Indic Parler-TTS** if the user wants a slow, clear reading with a caption like "very slow, very clear audio".
   - Fallback: the eSpeak NG hand-phoneme pipeline above, which needs no downloads.
3. **Human-recording mode:** given a local audio file plus start and end times, cut the clip and slow it with ffmpeg without changing pitch.
4. **Post-processing:** pauses between pādas, `loudnorm`, export to MP3 (192k mono).
5. **Verification:** the model can't listen. Print the phoneme or transliteration trace for review and tell the user to listen, and ask them to flag mispronounced words so they can be added to the overrides file.
6. **Speed control:** make pace a parameter (the user wants very slow, clear pronunciation).

### 6. Open questions to ask the user (use AskUserQuestion, don't assume)

- What OS and hardware do they have locally (Windows, macOS or Linux; does it have an NVIDIA GPU)? This decides EdgeSanskrit-TTS versus Vāgdhenu.
- Is network access to Hugging Face available locally (it was blocked in the cloud sandbox)?
- Should the skill be a Claude Code skill (SKILL.md plus scripts) in the project, or a personal skill under `~/.claude/skills/`?
- Which Sanskrit texts will they convert most (Gītā shlokas, Vedic mantras, stotras)? Vedic accents (svara) are not handled by any approach so far.
- What speed counts as "slow enough"? For example, ask for a reference recording they like, or a target seconds-per-line.
- Which reference chanter's voice is acceptable to use as the reference clip for EdgeSanskrit-TTS or Vāgdhenu (licensing and consent matter, and the Vāgdhenu author asks users not to impersonate the speaker)?

### 7. Suggested first prompt for Claude Code

> Read `sanskrit_tts_handoff.md`. Ask me the open questions in section 6 using AskUserQuestion, then set up EdgeSanskrit-TTS locally, generate Bhagavad Gītā 2.47 as a slow MP3, and compare it with the eSpeak version from section 2. Don't assume anything I haven't said. Tell me what I need to listen for, since you can't hear audio.

### 8. Caveats

- No neural model or recording was tested, and no audio was heard by the assistant. Everything about quality is unverified.
- Model details (sizes, speeds, licenses, features) come from the project pages as summarized in the session and could be out of date; check each repo's README before relying on them.
- The first MP3 (`bhagavad_gita_2_47_sanskrit.mp3`, about 14 s) was sent to the user in the chat and judged too robotic.