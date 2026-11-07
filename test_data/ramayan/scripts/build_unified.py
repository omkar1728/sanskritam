#!/usr/bin/env python3
"""Merge the three Ramayana sources into one JSON file per verse (pilot: Bala Kanda).

Usage: python3 -I build_unified.py <ramayan_dir> <kanda_key>
  kanda_key: baala ayodhya aranya kishkindha sundara yuddha uttara
  (a vulgate source dir that is absent/empty is treated as absent: critical-only output)

Sources (raw files in <ramayan_dir>/raw):
  smith  Baroda critical edition, Devanagari only (bombay.indology.info)
  net    valmikiramayan.net: Devanagari + English word-for-word + English translation
  in     valmikiramayan.in:  Devanagari + Hindi translation + Hindi word table

Verse numbers/boundaries differ between sources, so sources are aligned per sarga at half-verse
(line) level by text similarity. Every alignment row carries its similarity score; rows below
HIGH are flagged for human review, rows below MIN are never merged.
"""
import collections
import html
import json
import re
import sys
import unicodedata
from html.parser import HTMLParser
from pathlib import Path

KANDAS = {
    "baala": dict(number=1, name_sa="बालकाण्ड", name_en="Bala Kanda", smith="Ram01.txt", sargas=77),
    "ayodhya": dict(number=2, name_sa="अयोध्याकाण्ड", name_en="Ayodhya Kanda", smith="Ram02.txt", sargas=119),
    "aranya": dict(number=3, name_sa="अरण्यकाण्ड", name_en="Aranya Kanda", smith="Ram03.txt", sargas=75),
    "kishkindha": dict(number=4, name_sa="किष्किन्धाकाण्ड", name_en="Kishkindha Kanda", smith="Ram04.txt", sargas=67),
    "sundara": dict(number=5, name_sa="सुन्दरकाण्ड", name_en="Sundara Kanda", smith="Ram05.txt", sargas=68),
    "yuddha": dict(number=6, name_sa="युद्धकाण्ड", name_en="Yuddha Kanda", smith="Ram06.txt", sargas=128),
    "uttara": dict(number=7, name_sa="उत्तरकाण्ड", name_en="Uttara Kanda", smith="Ram07.txt", sargas=0),
}
DEV_DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")


# ---------------------------------------------------------------- helpers
def nfc(s):
    return unicodedata.normalize("NFC", s)


def clean(s):
    return re.sub(r"\s+", " ", nfc(html.unescape(s))).strip()


NASAL = {"क": "ङ", "ख": "ङ", "ग": "ङ", "घ": "ङ", "च": "ञ", "छ": "ञ", "ज": "ञ", "झ": "ञ",
         "ट": "ण", "ठ": "ण", "ड": "ण", "ढ": "ण", "त": "न", "थ": "न", "द": "न", "ध": "न",
         "प": "म", "फ": "म", "ब": "म", "भ": "म"}


def norm_for_compare(s):
    """Comparison key only (never stored as text): drops punctuation, spaces, verse numbers, leading
    om, and treats anusvara before a varga consonant as the matching nasal + virama."""
    s = nfc(s)
    s = re.sub(r"[|।॥\d०-९\.\-–,;:'’\"“”()\[\]]", "", s)
    s = s.replace("ऽ", "").replace("‌", "").replace("‍", "")
    s = re.sub(r"\s+", "", s)
    s = re.sub(r"^ॐ", "", s)
    # orthographic variants of the same sound: anusvara <-> homorganic nasal + virama, final म् <-> ं
    s = re.sub("[ङञणनम]्(?=[क-ह])", "ं", s)
    s = re.sub("म्$", "ं", s)
    s = s.replace("ँ", "ं").replace("ऩ", "न").replace("ऱ", "र").replace("ळ", "ल")
    return s


def itrans_to_dev(text):
    """Machine conversion of the net site's roman words. Marked machine_converted in the output."""
    from indic_transliteration import sanscript
    t = text.replace("~", "~")  # site uses j~naH for ज्ञ (valid ITRANS)
    t = re.sub(r"\bCha", "chha", t)
    return sanscript.transliterate(t, sanscript.ITRANS, sanscript.DEVANAGARI)


# ---------------------------------------------------------------- smith
def parse_smith(path):
    out = {}
    for line in path.read_text(encoding="utf-8").replace("\r", "").split("\n"):
        if not line or line.startswith("%"):
            continue
        m = re.match(r"^(\d)(\d{3})(\d{3})([a-z]) (.+)$", line)
        if not m:
            raise ValueError(f"smith: unparsable line {line!r}")
        _, sg, vs, pada, txt = m.groups()
        out.setdefault((int(sg), int(vs)), []).append((pada, nfc(txt.strip())))
    return out


def parse_smith_notes(path):
    """Parse the 'Notes on the electronic text' section of Ram00.txt into structured records."""
    lines = path.read_text(encoding="utf-8").replace("\r", "").split("\n")
    start = None
    for i, l in enumerate(lines[:-1]):
        if l.strip() == "Notes on the electronic text" and lines[i + 1].startswith("~"):
            start = i + 2
    if start is None:
        return []
    blocks, cur = [], []
    for l in lines[start:]:
        if not l.strip():
            if cur:
                blocks.append(cur)
            cur = []
        else:
            cur.append(l)
    if cur:
        blocks.append(cur)
    notes = []
    for b in blocks:
        ids = [m.group(1) for l in b if (m := re.match(r"^(\d{7}[a-z])\s", l))]
        if not ids:
            continue
        comment, stars, star = [], [], None
        for l in b:
            if re.match(r"^\d{7}[a-z]\s", l) or not l.startswith(" "):
                continue
            t = nfc(l.strip())
            m = re.search(r"Star passage (\S+) reads:\s*$", t)
            if m:
                comment.append(t)
                star = {"label": m.group(1), "lines": []}
                stars.append(star)
            elif star is not None:
                star["lines"].append(t)
            else:
                comment.append(t)
        notes.append({"smith_ids": ids, "comment": "\n".join(comment), "star_passages": stars})
    return notes


# ---------------------------------------------------------------- net
def parse_net_sarga(path, sarga):
    t = path.read_text(encoding="utf-8", errors="replace")
    title = re.search(r"<title>(.*?)</title>", t, re.S)
    intro_m = re.search(r"Introduction</?[^>]*>(.*?)(?=<p\s+class=\"verloc\">)", t, re.S)
    intro = clean(re.sub(r"<[^>]+>", " ", intro_m.group(1))) if intro_m else None
    groups = list(re.finditer(r'(?:<a\s+name\s*=\s*"Verse\d+"[^>]*>\s*</a>\s*)+', t))
    verses, skipped, page_kandas = {}, [], set()
    if not groups:  # some pages have no Verse anchors: one group per Sanskrit paragraph
        class _G:
            def __init__(self, m, n):
                self._m, self._n = m, n
            def start(self):
                return self._m.start()
            def group(self, _=0):
                return f'<a name="Verse{self._n}"></a>'
        groups = [_G(m, n + 1) for n, m in enumerate(re.finditer(r'<p\s+class="SanSloka">', t))]
    for gi, g in enumerate(groups):
        end = groups[gi + 1].start() if gi + 1 < len(groups) else len(t)
        part = t[g.start():end]
        anchors = [int(x) for x in re.findall(r'name\s*=\s*"Verse(\d+)"', g.group(0))]
        anchor = anchors[0]
        slokas = re.findall(r'<p\s+class="(?:SanSloka|ItrSloka)">(.*?)</p>', part, re.S)
        dev = next((s for s in slokas if "audio" not in s and re.search(r"[\u0900-\u097F]", s)), None)
        if dev is None:
            skipped.append(anchor)
            continue
        dev_txt = re.sub(r"<br\s*/?>", "\n", dev)
        dev_txt = re.sub(r"<[^>]+>", "", dev_txt)
        dev_txt = html.unescape(dev_txt)
        LOC = r"[|॥]+\s*([०-९0-9]+)\s*[-–.]\s*([०-९0-9]+)\s*[-–.]\s*([०-९0-9]+)"
        locs = re.findall(LOC, dev_txt)
        locator = ", ".join(f"{a}-{b}-{c}".translate(DEV_DIGITS) for a, b, c in locs) or None
        page_kandas.update(int(a.translate(DEV_DIGITS)) for a, _, _ in locs)
        body = re.sub(LOC, "", dev_txt)
        lines = [clean(x) for x in re.split(r"\n|\|(?=\s*$)", body) if clean(x)]
        prat = re.search(r'<p\s+class="pratipada">(.*?)</p>', part, re.S)
        words = []
        if prat:
            ph = prat.group(1)
            ph = re.sub(r"^\s*(<em>)?\s*\d+\.\s*", r"\1", ph)  # leading "1. "
            for em, mean in re.findall(r"<em>(.*?)</em>\s*=\s*(.*?)(?=<em>|$)", ph, re.S):
                roman = clean(re.sub(r"<[^>]+>", "", em))
                roman = re.sub(r"^\d+\.\s*", "", roman)
                words.append({"roman_itrans": roman,
                              "devanagari_machine_converted": itrans_to_dev(roman),
                              "english": clean(re.sub(r"<[^>]+>", "", mean)).rstrip(";").strip()})
        tat = re.search(r'<p\s+class="tat">(.*?)</p>', part, re.S)
        com = re.search(r'<p\s+class="comment">(.*?)</p>', part, re.S)
        verses[anchor] = {
            "anchor": anchor,
            "anchors": anchors,
            "locator": locator,
            "lines": lines,
            "english_translation": clean(re.sub(r"<[^>]+>", "", tat.group(1))) if tat else None,
            "english_word_by_word": words if prat else None,
            "english_word_by_word_raw": clean(re.sub(r"<[^>]+>", "", prat.group(1))) if prat else None,
            "commentary_en": clean(re.sub(r"<[^>]+>", "", com.group(1))) if com else None,
        }
    return {"title": clean(title.group(1)) if title else None, "intro": intro, "verses": verses,
            "kanda_from_page": sorted(page_kandas), "skipped_anchors_no_devanagari": skipped}


# ---------------------------------------------------------------- in
class InParser(HTMLParser):
    """Walks the .in page: one div.shloka-card per verse."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.cards = []
        self.cur = None
        self.depth = 0
        self.capture = None
        self.buf = []
        self.in_row = False
        self.cells = []
        self.header = {"title": None, "title_en": None, "count": None}
        self.hdr_i = 0

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        cls = a.get("class", "")
        if tag == "div" and "shloka-card" in cls.split():
            self.cur = {"verse_number": a.get("data-verse-number"), "id": a.get("id"),
                        "sanskrit_attr": a.get("data-sanskrit"), "hindi_attr": a.get("data-hindi"),
                        "locator": None, "dev_lines": [], "hindi": None, "words": []}
            self.cards.append(self.cur)
            self.depth = 1
            return
        if self.cur is not None and tag == "div":
            self.depth += 1
            if "shloka-sanskrit" in cls.split():
                self.capture = "dev"
                self.buf = []
        if self.cur is not None and tag == "br" and self.capture == "dev":
            self.buf.append("\n")
        if self.cur is not None and tag == "tr":
            self.in_row, self.cells = True, []
        if self.cur is not None and tag == "td" and self.in_row:
            self.capture, self.buf = "td", []
        if self.cur is not None and tag == "span" and self.capture is None:
            self.capture, self.buf = "span", []
        if self.cur is not None and tag == "span" and self.capture == "dev":
            pass

    def handle_endtag(self, tag):
        if self.cur is None:
            return
        if tag == "td" and self.capture == "td":
            self.cells.append(clean("".join(self.buf)))
            self.capture = None
        elif tag == "tr" and self.in_row:
            if len(self.cells) >= 2:
                self.cur["words"].append({"sanskrit": self.cells[0], "hindi": " ".join(self.cells[1:])})
            self.in_row = False
        elif tag == "span" and self.capture == "span":
            txt = clean("".join(self.buf))
            m = re.search(r"॥\s*(\d+\.\d+\.\d+[^॥]*)॥", txt)
            if m and not self.cur["locator"]:
                self.cur["locator"] = m.group(1).strip()
            elif self.cur["hindi"] is None and len(txt) > 12 and self.cur["locator"] is not None:
                self.cur["hindi"] = txt
            self.capture = None
        elif tag == "div":
            if self.capture == "dev":
                self.cur["dev_lines"] = [clean(x) for x in "".join(self.buf).split("\n") if clean(x)]
                self.capture = None
            self.depth -= 1
            if self.depth <= 0:
                self.cur = None

    def handle_data(self, data):
        if self.capture:
            self.buf.append(data)


def parse_in_sarga(path):
    t = path.read_text(encoding="utf-8", errors="replace")
    p = InParser()
    p.feed(t)
    head = re.search(r"(?:सर्ग|सर्ग)\s*\d+\s*:\s*([^<]+)</div>\s*<div[^>]*>([^<]+)</div>", html.unescape(t))
    cnt = re.search(r"कुल श्लोक:\s*(\d+)", html.unescape(t))
    verses = {}
    for c in p.cards:
        n = int(c["verse_number"])
        # the hindi translation is the data-hindi attribute (clean, single string)
        verses[n] = {
            "verse_number": n,
            "locator": c["locator"],
            "lines": c["dev_lines"],
            "hindi_translation": clean(c["hindi_attr"] or c["hindi"] or ""),
            "hindi_word_by_word": [w for w in c["words"] if w["sanskrit"]],
        }
    return {"title_hi": clean(head.group(1)) if head else None,
            "title_en": clean(head.group(2)) if head else None,
            "declared_verse_count": int(cnt.group(1)) if cnt else None,
            "verses": verses}


# ---------------------------------------------------------------- merge
def punctuate_critical(lines):
    """Derived: danda after the first half-verse, double danda at the end. Only for 2-line verses."""
    if len(lines) == 2:
        return f"{lines[0]} ।\n{lines[1]} ॥"
    return None


from difflib import SequenceMatcher

MIN, HIGH = 0.60, 0.85  # similarity thresholds (flag-for-review / never-merge)
BAND = 80


def sim(a, b):
    if a == b:
        return 1.0
    sm = SequenceMatcher(None, a, b, autojunk=False)
    if sm.real_quick_ratio() < MIN or sm.quick_ratio() < MIN:
        return 0.0
    return sm.ratio()


def align(a_keys, b_keys):
    """Monotonic max-similarity alignment. Returns dict a_index -> (b_index, similarity)."""
    n, m = len(a_keys), len(b_keys)
    score = [[0.0] * (m + 1) for _ in range(n + 1)]
    back = [[0] * (m + 1) for _ in range(n + 1)]  # 1 diag, 2 up(skip a), 3 left(skip b)
    sims = {}
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            best, bk = score[i - 1][j], 2
            if score[i][j - 1] > best:
                best, bk = score[i][j - 1], 3
            if abs(i - j) <= BAND:
                sv = sim(a_keys[i - 1], b_keys[j - 1])
                if sv >= MIN and score[i - 1][j - 1] + sv >= best:
                    best, bk = score[i - 1][j - 1] + sv, 1
                    sims[(i - 1, j - 1)] = sv
            score[i][j], back[i][j] = best, bk
    out, i, j = {}, n, m
    while i > 0 and j > 0:
        if back[i][j] == 1:
            out[i - 1] = (j - 1, sims[(i - 1, j - 1)])
            i, j = i - 1, j - 1
        elif back[i][j] == 2:
            i -= 1
        else:
            j -= 1
    return out


def word_diffs(a, b):
    """Token-level differences between two raw lines, for human review."""
    aw, bw = a.replace("|", "").replace("।", "").replace(";", "").split(), b.replace("|", "").replace("।", "").replace(";", "").split()
    sm = SequenceMatcher(None, aw, bw, autojunk=False)
    return [{"a": " ".join(aw[i1:i2]), "b": " ".join(bw[j1:j2])}
            for tag, i1, i2, j1, j2 in sm.get_opcodes() if tag != "equal"]


def strip_punct(line):
    return clean(re.sub(r"[|।॥]+\s*$", "", line))


GP_NUM_TAIL = re.compile(r"\s*[।॥|]*\s*[०-९0-9][०-९0-9\s\-–,.]*[।॥|]*\s*$")


def gp_clean_line(line):
    """Gita Press line: drop the printed verse number (e.g. '॥ ५१॥') and danda marks at the end."""
    return strip_punct(GP_NUM_TAIL.sub("", clean(line)))


def load_gp(path):
    """Gita Press parsed units grouped by (vulgate) sarga. Null sarga -> previous unit's sarga."""
    units = json.loads(path.read_text(encoding="utf-8"))
    by, cur = {}, None
    nxt = [None] * len(units)
    later = None
    for i in range(len(units) - 1, -1, -1):
        if units[i].get("sarga") is not None:
            later = units[i]["sarga"]
        nxt[i] = later
    for i, u in enumerate(units):
        u = dict(u)
        u["_inferred"] = u.get("sarga") is None
        if u["sarga"] is None:
            u["sarga"] = cur if cur is not None else (nxt[i] if nxt[i] is not None else 1)
        cur = u["sarga"]
        by.setdefault(int(u["sarga"]), []).append(u)
    return by, len(units)


def gp_flatten(units):
    out = []
    for ui, u in enumerate(units):
        for l in u.get("sanskrit_lines") or []:
            c = gp_clean_line(l)
            if c:
                out.append((ui, c))
    return out


def main():
    root = Path(sys.argv[1])
    kkey = sys.argv[2]
    k = KANDAS[kkey]
    raw, out = root / "raw", root / "unified" / kkey
    smith = parse_smith(raw / "smith" / k["smith"])
    smith_sargas = {s for s, _ in smith}
    NS = k["sargas"]
    net_dir, in_dir = raw / "net" / kkey, raw / "in" / kkey
    has_net = NS > 0 and net_dir.is_dir() and any(net_dir.glob("sans*.htm"))
    has_in = in_dir.is_dir() and any(in_dir.glob("sarga*.html"))
    GP, gp_total = {}, 0
    gp_path = raw / "gitapress" / "parsed" / f"{kkey}.json"
    if gp_path.is_file():
        GP, gp_total = load_gp(gp_path)
    has_gp = bool(GP)
    NSN = NS if has_net else 0  # sargas that have net pages
    has_vulgate = has_net or has_gp
    NS = max(NSN, max(GP) if GP else 0) if has_vulgate else 0
    gp_unparsed = gp_skipped = None
    for nm in ("unparsed", "skipped"):
        fp = raw / "gitapress" / "parsed" / f"{kkey}_{nm}.txt"
        v = len(fp.read_text(encoding="utf-8", errors="replace").splitlines()) if fp.is_file() else None
        if nm == "unparsed":
            gp_unparsed = v
        else:
            gp_skipped = v
    notes_all = [n for n in parse_smith_notes(raw / "smith" / "Ram00.txt") if int(n["smith_ids"][0][0]) == k["number"]]
    notes_by_first = {n["smith_ids"][0]: n for n in notes_all}
    attached_notes = set()
    report = {"kanda": kkey, "thresholds": {"never_merge_below": MIN, "flag_below": HIGH},
              "per_sarga": {}, "problems": [], "net_locator_anomalies": [], "low_confidence": [], "unmatched": [],
              "sources_present": {"smith": True, "net": has_net, "in": has_in, "gp": has_gp},
              "gitapress_unparsed_lines": gp_unparsed, "gitapress_skipped_lines": gp_skipped, "unattached_notes": [],
              "critical_only_sargas": []}
    totals = dict(docs=0, critical_docs=0, vulgate_only_docs=0, rows=0,
                  rows_all_three=0, rows_smith_only=0, rows_vulgate_only=0, low_conf_rows=0, docs_with_gp=0)

    audit = collections.Counter()
    used_net_units, used_in_units, used_gp_units = set(), set(), set()
    NET, IND = {}, {}
    for vs in range(1, NSN + 1):
        try:
            NET[vs] = parse_net_sarga(net_dir / f"sans{vs}.htm", vs)
            kp = NET[vs]["kanda_from_page"]
            if kp and kp != [k["number"]]:
                report["net_locator_anomalies"].append(f"sarga {vs}: net page locators name kanda(s) {kp}, expected {k['number']}")
            if NET[vs]["skipped_anchors_no_devanagari"]:
                report["problems"].append(f"sarga {vs}: net anchors without devanagari verse skipped: {NET[vs]['skipped_anchors_no_devanagari']}")
        except FileNotFoundError:
            report["problems"].append(f"sarga {vs}: net file missing")
        except Exception as e:  # never crash on odd markup
            report["problems"].append(f"sarga {vs}: net parse error {type(e).__name__}: {e}")
        if has_in:
            try:
                IND[vs] = parse_in_sarga(in_dir / f"sarga{vs}.html")
            except FileNotFoundError:
                report["problems"].append(f"sarga {vs}: in file missing")
            except Exception as e:
                report["problems"].append(f"sarga {vs}: in parse error {type(e).__name__}: {e}")

    # critical sarga -> vulgate sarga, found by text (the two editions number sargas differently)
    if has_net:
        vkeys = {vs: [norm_for_compare(l) for a_ in sorted(n["verses"]) for l in n["verses"][a_]["lines"]]
                 for vs, n in NET.items()}
    else:  # no net: gp is the vulgate reference for mapping critical sargas
        vkeys = {vs: [norm_for_compare(t) for _, t in gp_flatten(us)] for vs, us in GP.items()}
    cmap, prev, last_off, crit_only = {}, 1, 0, []
    report["sarga_map_critical_to_vulgate"] = {}

    def _tri(x):
        return {x[i:i + 3] for i in range(max(1, len(x) - 2))}
    vtri = {vs: [(x, _tri(x)) for x in xs] for vs, xs in vkeys.items()}

    def _hit(ln, lt, vs):
        for x, xt in vtri.get(vs, []):
            if x == ln:
                return True
            if len(lt & xt) / max(1, len(lt | xt)) >= 0.4 and sim(ln, x) >= 0.8:
                return True
        return False
    for cs in (sorted(smith_sargas) if has_vulgate else []):
        allv = [norm_for_compare(t) for (s_, v), ls in sorted(smith.items()) if s_ == cs for _, t in ls]
        allv = [x for x in allv if x]
        step = max(1, len(allv) / 15)
        sample = [allv[int(i * step)] for i in range(min(15, len(allv)))]
        need = 1 if len(allv) < 5 else 2
        hist = {}
        for vs in range(prev, min(prev + 26, NS + 1)):
            h = sum(1 for ln in sample if _hit(ln, _tri(ln), vs))
            if h >= need:
                hist[vs] = h
        if hist:
            mx = max(hist.values())
            vs = min(v for v, h in hist.items() if h == mx)  # earliest best (monotone)
            how = f"text_match_{hist[vs]}_of_{len(sample)}_sampled_lines"
        else:
            vs = min(cs + last_off, NS)
            how = "INFERRED_from_previous_offset_no_text_match"
            if vs in cmap.values() or vs not in vkeys or vs < prev:
                crit_only.append(cs)
                report["critical_only_sargas"].append({"critical_sarga": cs, "why": "no text match and inferred vulgate sarga taken/absent"})
                continue
            report["problems"].append(f"critical sarga {cs}: no text match, inferred vulgate sarga {vs}")
        if vs in cmap.values():
            crit_only.append(cs)
            report["critical_only_sargas"].append({"critical_sarga": cs, "why": f"vulgate sarga {vs} already matched by an earlier critical sarga"})
            continue
        cmap[cs] = vs
        prev, last_off = vs, vs - cs
        report["sarga_map_critical_to_vulgate"][cs] = {"vulgate_sarga": vs, "how": how}
    inv = {v: c for c, v in cmap.items()}
    report["vulgate_sargas_without_critical_counterpart"] = [v for v in range(1, NS + 1) if v not in inv]

    if has_vulgate:
        plan = [(vs, inv.get(vs), vs) for vs in range(1, NS + 1)] + [(NS + cs, cs, None) for cs in crit_only]
    else:
        plan = [(cs, cs, None) for cs in sorted(smith_sargas)]
    for sg, csg, vsg in plan:
        net, ind = NET.get(vsg), IND.get(vsg)
        gps = GP.get(vsg) if vsg is not None else None

        # ---- flatten each source to half-lines with a pointer to its meaning unit
        S = [(v, p, t) for (s_, v), ls in sorted(smith.items()) if csg is not None and s_ == csg for p, t in ls]
        N, I = [], []
        net_units = []
        if net:
            seen = set()
            for a in sorted(net["verses"]):
                u = net["verses"][a]
                ui = len(net_units)
                net_units.append(u)
                N += [(ui, strip_punct(l)) for l in u["lines"] if strip_punct(l)]
        in_units = []
        if ind:
            for n_ in sorted(ind["verses"]):
                u = ind["verses"][n_]
                ui = len(in_units)
                in_units.append(u)
                I += [(ui, strip_punct(re.sub(r"^ॐ\s*", "", l))) for l in u["lines"] if strip_punct(re.sub(r"^ॐ\s*", "", l))]
        gp_units = gps or []
        G = gp_flatten(gp_units)
        keys = {"smith": [norm_for_compare(t) for _, _, t in S], "net": [norm_for_compare(t) for _, t in N],
                "in": [norm_for_compare(t) for _, t in I], "gp": [norm_for_compare(t) for _, t in G]}

        # ---- build rows in order; hub = net lines, or the critical (smith) lines when net is empty
        hub = "net" if N else "smith"
        hk = keys[hub]
        others = [n_ for n_ in ("smith", "in", "gp") if n_ != hub]
        o2h = {n_: align(keys[n_], hk) for n_ in others}
        h2o = {n_: {j: (i, sv) for i, (j, sv) in o2h[n_].items()} for n_ in others}
        ptr = {n_: 0 for n_ in others}
        used = {n_: set() for n_ in ("smith", "in", "gp")}

        def blank():
            return {"smith": None, "net": None, "in": None, "gp": None}
        rows = []
        for j in range(len(hk)):
            row = blank()
            row[hub] = j
            for n_ in others:
                m = h2o[n_].get(j)
                if m:
                    while ptr[n_] < m[0]:
                        x = ptr[n_]
                        if x not in used[n_] and x not in o2h[n_]:
                            r_ = blank(); r_[n_] = x; rows.append(r_); used[n_].add(x)
                        ptr[n_] += 1
                    ptr[n_] = max(ptr[n_], m[0] + 1)
                    row[n_] = m[0]
                    row[f"sim_{n_}_{hub}"] = m[1]
                    used[n_].add(m[0])
            rows.append(row)
        for n_, cnt in (("smith", len(S)), ("in", len(I)), ("gp", len(G))):
            if n_ == hub:
                continue
            for x in range(cnt):
                if x not in used[n_]:
                    r_ = blank(); r_[n_] = x; rows.append(r_)
        vk = "net" if N else "gp"  # which source counts as "the vulgate match" for critical lines

        # ---- group rows into docs: by smith verse; others become vulgate-only docs after prior verse
        docs, cur, last_cv = [], None, None
        for r in rows:
            if r["smith"] is not None:
                cv = S[r["smith"]][0]
                if cur is None or cur["cv"] != cv or cur["vulgate_only"]:
                    cur = {"cv": cv, "vulgate_only": False, "rows": [], "after": None}
                    docs.append(cur)
                last_cv = cv
            else:
                gu_r = G[r["gp"]][0] if r["gp"] is not None and r["net"] is None else None
                if (cur is None or not cur["vulgate_only"] or cur["after"] != last_cv
                        or (gu_r is not None and cur.get("last_gu") not in (None, gu_r))):
                    cur = {"cv": None, "vulgate_only": True, "rows": [], "after": last_cv}
                    docs.append(cur)
                if gu_r is not None:
                    cur["last_gu"] = gu_r
            cur["rows"].append(r)

        used_nu = {N[r["net"]][0] for r in rows if r["net"] is not None}
        used_iu = {I[r["in"]][0] for r in rows if r["in"] is not None}
        used_gu = {G[r["gp"]][0] for r in rows if r["gp"] is not None}
        for ui in range(len(net_units)):
            if ui not in used_nu:
                docs.append({"cv": None, "vulgate_only": True, "rows": [], "after": None, "extra_nu": [ui], "extra_iu": [], "extra_gu": []})
        for ui in range(len(in_units)):
            if ui not in used_iu:
                docs.append({"cv": None, "vulgate_only": True, "rows": [], "after": None, "extra_nu": [], "extra_iu": [ui], "extra_gu": []})
        for ui in range(len(gp_units)):
            if ui not in used_gu:
                docs.append({"cv": None, "vulgate_only": True, "rows": [], "after": None, "extra_nu": [], "extra_iu": [], "extra_gu": [ui]})

        sdir = out / f"sarga_{sg:03d}"
        sdir.mkdir(parents=True, exist_ok=True)
        counts = dict(smith_lines=len(S), net_lines=len(N), in_lines=len(I),
                      smith_verses=len({v for v, _, _ in S}), net_blocks=len(net_units),
                      in_verses=len(in_units), gp_lines=len(G), gp_units=len(gp_units), in_declared=ind["declared_verse_count"] if ind else None,
                      docs=len(docs))
        report["per_sarga"][sg] = counts
        (sdir / "_sarga.json").write_text(json.dumps({
            "kanda": k["number"], "sarga": sg, "critical_sarga": csg, "vulgate_sarga": vsg,
            "critical_only_sarga": vsg is None,
            "title_hi_from_in": ind["title_hi"] if ind else None,
            "title_en_from_in": ind["title_en"] if ind else None,
            "intro_en_from_net": net["intro"] if net else None,
            "counts": counts}, ensure_ascii=False, indent=2), encoding="utf-8")

        audit["smith_lines_in"] += len(S); audit["net_lines_in"] += len(N); audit["in_lines_in"] += len(I)
        audit["gp_lines_in"] += len(G); audit["gp_units_in"] += len(gp_units)
        audit["net_units_in"] += len(net_units); audit["in_units_in"] += len(in_units)
        for seq, d in enumerate(docs, 1):
            did = f"{kkey}-{sg:03d}-{seq:03d}"
            fname = f"verse_{seq:03d}.json"
            lines_s, lines_n, lines_i, lines_g, align_rows, flags = [], [], [], [], [], []
            nu = {u: True for u in d.get("extra_nu", [])}
            iu = {u: True for u in d.get("extra_iu", [])}
            gu = {u: True for u in d.get("extra_gu", [])}
            for r in d["rows"]:
                ls = S[r["smith"]][2] if r["smith"] is not None else None
                ln = N[r["net"]][1] if r["net"] is not None else None
                li = I[r["in"]][1] if r["in"] is not None else None
                lg = G[r["gp"]][1] if r["gp"] is not None else None
                if lg: lines_g.append(lg)
                if r["gp"] is not None: gu.setdefault(G[r["gp"]][0], True)
                if ls: lines_s.append(ls)
                if ln: lines_n.append(ln)
                if li: lines_i.append(li)
                if r["net"] is not None: nu.setdefault(N[r["net"]][0], True)
                if r["in"] is not None: iu.setdefault(I[r["in"]][0], True)
                sims = {kk: r.get(kk) for kk in ("sim_smith_net", "sim_in_net", "sim_gp_net", "sim_in_smith", "sim_gp_smith") if r.get(kk) is not None}
                conf = "n/a"
                if r["smith"] is not None and r["net"] is not None and r["in"] is not None:
                    totals["rows_all_three"] += 1
                if sims:
                    conf = "high" if min(sims.values()) >= HIGH else "LOW"
                    if conf == "LOW":
                        totals["low_conf_rows"] += 1
                        report["low_confidence"].append({"id": did, "sims": sims, "smith": ls, "net": ln, "in": li, "gp": lg})
                if r["smith"] is not None and r[vk] is None and vsg is not None:
                    totals["rows_smith_only"] += 1
                    report["unmatched"].append({"id": did, "only_in": "smith", "text": ls})
                if r["smith"] is None:
                    totals["rows_vulgate_only"] += 1
                diffs = {}
                if ls and ln and ls.replace(";", "") != ln: diffs["smith_vs_net"] = word_diffs(ls, ln)
                if ln and li and ln != li: diffs["net_vs_in"] = word_diffs(ln, li)
                if lg and ln and lg != ln: diffs["net_vs_gp"] = word_diffs(ln, lg)
                if lg and ls and not ln and ls.replace(";", "") != lg: diffs["smith_vs_gp"] = word_diffs(ls, lg)
                align_rows.append({"smith": ls, "net": ln, "in": li, "gp": lg, "similarity": sims,
                                   "confidence": conf, "word_diffs": diffs})
                totals["rows"] += 1
            if d["vulgate_only"]:
                flags.append("vulgate_only_no_critical_edition_counterpart")
            if not d["rows"]:
                flags.append("meaning_only_unit_no_verse_text_in_that_source")
            if any(a_["confidence"] == "LOW" for a_ in align_rows):
                flags.append("low_confidence_alignment")
            if vsg is None:
                flags.append("critical_sarga_without_vulgate_counterpart")
            elif any(a_["smith"] and not a_[vk] for a_ in align_rows):
                flags.append("critical_line_without_vulgate_match")
            if any(a_["net"] and not a_["smith"] and not d["vulgate_only"] for a_ in align_rows):
                flags.append("vulgate_net_line_without_critical_match")
            if vk == "gp" and any(a_["gp"] and not a_["smith"] and not d["vulgate_only"] for a_ in align_rows):
                flags.append("vulgate_gp_line_without_critical_match")
            if any(gp_units[u]["_inferred"] for u in gu):
                flags.append("gp_sarga_inferred")
            if any(a_["in"] and not a_["net"] for a_ in align_rows) or any(a_["net"] and not a_["in"] for a_ in align_rows):
                flags.append("net_in_line_mismatch")

            def net_meta(ui):
                u = net_units[ui]
                spill = len(u["lines"]) > sum(1 for r in d["rows"] if r["net"] is not None and N[r["net"]][0] == ui)
                return u, spill
            en_tr, en_ww, en_cm, hi_tr, hi_ww = [], [], [], [], []
            for ui in nu:
                u, spill = net_meta(ui)
                base = {"source": "valmikiramayan.net", "net_locator": u["locator"], "spans_beyond_this_verse": spill}
                en_tr.append({**base, "translator": "K. M. K. Murthy / Desiraju Hanumanta Rao", "text": u["english_translation"]})
                if u["english_word_by_word"] is not None:
                    en_ww.append({**base, "note": "devanagari_machine_converted is our ITRANS->Devanagari conversion, unchecked",
                                  "words": u["english_word_by_word"]})
                if u["commentary_en"]:
                    en_cm.append({**base, "text": u["commentary_en"]})
            for ui in iu:
                u = in_units[ui]
                spill = len(u["lines"]) > sum(1 for r in d["rows"] if r["in"] is not None and I[r["in"]][0] == ui)
                base = {"source": "valmikiramayan.in", "in_locator": u["locator"], "spans_beyond_this_verse": spill,
                        "provenance": "unverified: site states no translator/author"}
                hi_tr.append({**base, "text": u["hindi_translation"]})
                hi_ww.append({**base, "words": u["hindi_word_by_word"]})
            hi_gp, gp_refs, gp_ocr = [], [], set()
            for ui in gu:
                u = gp_units[ui]
                spill = len(u["sanskrit_lines"]) > sum(1 for r in d["rows"] if r["gp"] is not None and G[r["gp"]][0] == ui)
                gp_refs.append(u.get("verse_ref") or "?")
                gp_ocr.update(u.get("ocr_flags") or [])
                hi_gp.append({"source": "Gita Press, Gorakhpur via archive.org OCR",
                              "provenance": "OCR, unverified; rights: uploader label CC0, original copyright may remain",
                              "verse_ref": u.get("verse_ref"), "ocr_flags": u.get("ocr_flags") or [],
                              "spans_beyond_this_verse": spill, "text": (u.get("hindi") or "").strip() or None})
            if any(x["spans_beyond_this_verse"] for x in en_tr + hi_tr + hi_gp):
                flags.append("meaning_unit_spans_multiple_verses")
            doc = {
                "id": did,
                "kanda": {"number": k["number"], "name_sa": k["name_sa"], "name_en": k["name_en"]},
                "sarga": sg,
                "seq_in_sarga": seq,
                "refs": {
                    "critical_smith": None if d["cv"] is None and not any(r["smith"] is not None for r in d["rows"]) else {
                        "sarga": csg, "verse": d["cv"]},
                    "vulgate_sarga": vsg,
                    "vulgate_net_locators": sorted({net_units[u]["locator"] or "?" for u in nu}),
                    "vulgate_in_locators": sorted({in_units[u]["locator"] or "?" for u in iu}),
                    "vulgate_gitapress_refs": sorted(set(gp_refs)),
                },
                "kind": "vulgate_only" if d["vulgate_only"] else "critical",
                "text": {
                    "critical_smith": None if not lines_s else {
                        "source": "Baroda Critical Edition, typed Tokunaga, standardised Smith (bombay.indology.info)",
                        "smith_ids": [f"{k['number']}{csg:03d}{S[r['smith']][0]:03d}{S[r['smith']][1]}" for r in d["rows"] if r["smith"] is not None],
                        "lines": lines_s,
                        "punctuated_derived": punctuate_critical(lines_s)},
                    "vulgate_net": None if not lines_n else {
                        "source": "valmikiramayan.net (edition not named)", "lines": lines_n,
                        "locators": sorted({net_units[u]["locator"] or "?" for u in nu})},
                    "vulgate_in": None if not lines_i else {
                        "source": "valmikiramayan.in (edition not named)", "lines": lines_i,
                        "locators": sorted({in_units[u]["locator"] or "?" for u in iu})},
                    "vulgate_gitapress": None if not lines_g else {
                        "source": "Gita Press, Gorakhpur via archive.org OCR (unverified)", "lines": lines_g,
                        "ocr_flags": sorted(gp_ocr), "refs": sorted(set(gp_refs))},
                },
                "alignment": align_rows,
                "meanings": {
                    "english_translation": en_tr or None,
                    "english_word_by_word": en_ww or None,
                    "english_commentary": en_cm or None,
                    "hindi_translation": hi_tr or None,
                    "hindi_word_by_word": hi_ww or None,
                    "hindi_translation_gitapress": hi_gp or None,
                },
                "flags": flags,
                "review_status": "unreviewed",
            }
            if any(";" in x for x in lines_s):
                doc["text"]["critical_smith"]["pada_split"] = [
                    {"line_index": i, "padas": x.split(";")} for i, x in enumerate(lines_s) if ";" in x]
            nts = [notes_by_first[i] for i in doc["text"]["critical_smith"]["smith_ids"] if i in notes_by_first] \
                if doc["text"]["critical_smith"] else []
            if nts:
                doc["critical_edition_notes"] = nts
                attached_notes.update(n["smith_ids"][0] for n in nts)
            (sdir / fname).write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            totals["docs"] += 1
            audit["smith_lines_out"] += len(lines_s); audit["net_lines_out"] += len(lines_n); audit["in_lines_out"] += len(lines_i)
            audit["gp_lines_out"] += len(lines_g)
            used_gp_units.update((sg, u) for u in gu)
            if lines_g: totals["docs_with_gp"] += 1
            used_net_units.update((sg, u) for u in nu); used_in_units.update((sg, u) for u in iu)
            totals["vulgate_only_docs" if d["vulgate_only"] else "critical_docs"] += 1

    audit["smith_lines_source"] = sum(len(v) for v in smith.values())
    report["unattached_notes"] = [n for n in notes_all if n["smith_ids"][0] not in attached_notes]
    audit["net_units_out"], audit["in_units_out"] = len(used_net_units), len(used_in_units)
    audit["gp_units_out"], audit["gp_units_source"] = len(used_gp_units), gp_total
    report["completeness_audit"] = dict(audit)
    report["completeness_ok"] = all(audit[k_ + "_in"] == audit[k_ + "_out"] for k_ in
                                    ("smith_lines", "net_lines", "in_lines", "net_units", "in_units", "gp_lines", "gp_units")) \
        and audit["gp_units_in"] == audit["gp_units_source"] \
        and audit["smith_lines_in"] == audit["smith_lines_source"]
    totals["completeness_ok"] = report["completeness_ok"]
    totals.update(kanda=kkey, sargas_output=len(plan), critical_only_sargas=len(plan) - sum(1 for p in plan if p[2] is not None) if has_vulgate else len(plan),
                  notes_attached=len(attached_notes), notes_unattached=len(report["unattached_notes"]),
                  smith_lines=audit["smith_lines_in"], net_lines=audit["net_lines_in"], in_lines=audit["in_lines_in"], gp_lines=audit["gp_lines_in"])
    report["totals"] = totals
    (out / "_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"totals": totals, "problems": report["problems"][:10],
                      "low_confidence": len(report["low_confidence"]),
                      "unmatched_smith_lines": len(report["unmatched"])}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
