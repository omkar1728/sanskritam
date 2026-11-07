#!/usr/bin/env python3
"""Parse Gita Press Valmiki Ramayan OCR text into per-kanda JSON units.

Usage: python3 -I parse_gitapress.py [raw_dir]   (default: ../raw/gitapress)
Writes parsed/<key>.json, parsed/<key>_unparsed.txt, parsed/<key>_skipped.txt,
parsed/<key>_titles.json (sarga headings + Hindi titles), parsed/summary.json.
OCR text is kept verbatim (whitespace + NFC normalisation only).
"""
import json, os, re, sys, unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
RAW = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "..", "raw", "gitapress")
OUT = os.path.join(RAW, "parsed")

KANDAS = [  # key, number, volume, Devanagari name prefix
    ("baala", 1, "vol1", "बाल"), ("ayodhya", 2, "vol1", "अयोध्या"),
    ("aranya", 3, "vol1", "अरण्य"), ("kishkindha", 4, "vol1", "किष्किन्धा"),
    ("sundara", 5, "vol2", "सुन्दर"), ("yuddha", 6, "vol2", "युद्ध"),
    ("uttara", 7, "vol2", "उत्तर"),
]
KNOWN = {"baala": 77, "ayodhya": 119, "aranya": 75, "kishkindha": 67,
         "sundara": 68, "yuddha": 128, "uttara": 111}

DEV = re.compile(r"[ऀ-ॿ]")
DIG = str.maketrans("०१२३४५६७८९", "0123456789")
NUM = r"[०-९0-9]{1,3}"
# verse-end markers (OCR varies): "॥ १२॥", "१२॥", "॥ १२", trailing bare "॥", "॥१-१-१॥"
MARK_A = re.compile(r"(?:॥|\|\||II)?\s*((?:%s)(?:\s*[-–।.,]\s*%s)*)\s*(?:॥|\|\||II)\s*$" % (NUM, NUM))
MARK_B = re.compile(r"॥\s*((?:%s)(?:\s*[-–।.,]\s*%s)*)\s*$" % (NUM, NUM))
MARK_C = re.compile(r"॥\s*$")
HEADING = re.compile(r"^[\s|]*(?:[^\s॥।]+\s+){0,2}सर्ग[ःः:]?(?:\s*\S{1,3}){0,2}\s*[।|]?\s*$")
COLOPHON = re.compile(r"^\s*(?:इत्या\S*|\S*मद्रामायणे.*)\s.*सर्ग|^\W*:?\s*सर्ग[ःः:]?\s*॥")
COLOPHON_NUM = re.compile(r"(%s)\s*(?:॥|\|)*\s*$" % NUM)
RUNHEAD = re.compile(r"(काण्डे|काण्डम्|काण्ड)\S*\s+.*सर्ग|^\s*[०-९0-9]*\s*\S*काण्डे\S*\s+\S+\s+सर्गः")


def norm(s):
    return re.sub(r"[ \t ]+", " ", unicodedata.normalize("NFC", s)).strip()


def toint(s):
    try:
        return int(s.translate(DIG))
    except ValueError:
        return None


def marker(line):
    """Return (kind, raw, first_int) if the line ends with a verse-end marker."""
    m = MARK_B.search(line) or MARK_A.search(line)
    if m:
        raw = m.group(1)
        first = re.match(r"[०-९0-9]+", raw)
        return "num", raw, toint(first.group(0)) if first else None
    if MARK_C.search(line):
        return "bare", "॥", None
    return None


def find_starts(lines, vol, kandas):
    res = {}
    for key, n, v, name in kandas:
        if v != vol:
            continue
        pat = re.compile(r"^[\s|(]*%sकाण्डम्\W*[\s|)]*$" % name)
        for i, l in enumerate(lines):
            if pat.match(l) and any("सर्ग" in x for x in lines[i + 1:i + 9]):
                res[key] = i
                break
    return res


HINDI_WORDS = set("है हैं था थे थी गया गये गयी किया करते करता करने हो हुआ हुए हुई और में से को का के की ने यह वह वे उन उस इस तो भी कि नहीं तथा जो जब तब वहाँ यहाँ मैं मुझे तुम तुम्हें हम आप अपने अपना अपनी उनके उनकी उसके उसकी इसके कर रहे रही रहा थीं तक सहित लिये द्वारा".split())
HINDI_SUF = re.compile(r"(?:में|से|को|के|की|का|तक|सहित|द्वारा|लिये|वाला|वाले|वाली|हुए|करके|कर)$")


def hindi_score(t):
    n = 0
    for w in re.findall(r"[\u0900-\u097F]+", t):
        w2 = w.rstrip("\u200c\u200d")
        if w2 in HINDI_WORDS or (len(w2) > 3 and HINDI_SUF.search(w2)):
            n += 1
    return n


def is_sa_line(t):
    """Sanskrit half-line: ends with danda-like punctuation and has no Hindi function word."""
    if not re.search(r"[।!|,;:.\-]\s*$", t):
        return False
    return hindi_score(t) == 0


def tail_run(buf):
    """Number of Sanskrit half-lines (ending '।') directly before the final marker line."""
    k = 0
    j = len(buf) - 2
    while j >= 0 and is_sa_line(buf[j][1]):
        k += 1
        j -= 1
    return k


def parse_kanda(lines, start, end, key, knum):
    units, unparsed, skipped, titles = [], [], [], []
    S = {"sarga": 0, "open": False, "buf": [], "first": False, "implicit": False,
         "lastv": 0, "pend": None, "expect": "S", "interp": False, "ipn": 0}
    heads = 0

    def mk(sarga, v, conf, sl, hl, flags, raws):
        allr = [x[0] for x in sl + hl]
        u = {"kanda": knum, "sarga": None if S["interp"] else sarga,
             "verse_ref": "%d.%d%s.%d" % (knum, sarga, ("p%d" % S["ipn"]) if S["interp"] else "", v),
             "verse_ref_confidence": conf,
             "sanskrit_lines": [t for _, t in sl],
             "hindi": norm(" ".join(t for _, t in hl)),
             "source_line_start": min(allr), "source_line_end": max(allr),
             "ocr_flags": flags, "marker_raw": raws}
        units.append(u)
        return u

    def sflags():
        return ["sarga_heading_missing_inferred"] if S["implicit"] else []

    def close_sarga(colo=None):
        p = S["pend"]
        if p:
            p["ocr_flags"].append("hindi_missing")
            S["pend"] = None
        for ln, t in S["buf"]:
            unparsed.append((ln, "trailing-without-marker: " + t))
        S["buf"] = []
        if colo is not None and S["open"] and not S["interp"] and colo != S["sarga"]:
            for u in units:
                if u["sarga"] == S["sarga"]:
                    u["ocr_flags"].append("sarga_colophon_number_%s_differs" % colo)
        S["open"] = False; S["expect"] = "S"; S["lastv"] = 0

    def open_sarga(implicit, interp=False):
        if not interp:
            S["sarga"] += 1
        S["interp"] = interp
        if interp:
            S["ipn"] += 1
        S["nv"] = 0
        S.update(open=True, first=True, implicit=implicit, lastv=0, expect="S", pend=None, buf=[])

    def take_S(buf):
        flags = []
        k = tail_run(buf)
        if k == 0 and len(buf) > 1 and hindi_score(buf[-2][1]) == 0:
            k = 1; flags.append("danda_missing_sanskrit_line_guessed")
        sl = buf[len(buf) - 1 - k:]
        lead = buf[:len(buf) - 1 - k]
        if lead:
            if S["first"]:
                if titles:
                    titles[-1]["title"] = " ".join(t for _, t in lead)
                    titles[-1]["title_lines"] = [lead[0][0], lead[-1][0]]
            else:
                for ln, t in lead:
                    unparsed.append((ln, "leading-before-verse: " + t))
                flags.append("leading_text_before_sanskrit_moved_to_unparsed")
        S["first"] = False
        return sl, flags

    def finish_pend_with_hindi(hl, m):
        p = S["pend"]
        S["pend"] = None
        p["hindi"] = norm(" ".join(t for _, t in hl))
        p["source_line_end"] = max(p["source_line_end"], hl[-1][0])
        p["marker_raw"].append(m[1])
        if m[0] == "bare":
            p["ocr_flags"].append("hindi_bare_marker_no_digits")
        pv = int(p["verse_ref"].split(".")[2])
        rng = [toint(x) for x in re.findall(r"[०-९0-9]+", m[1])]
        if len(rng) > 1:
            p["ocr_flags"].append("hindi_marker_range_" + m[1].translate(DIG))
            if rng[0] < pv:
                for u in reversed(units[:-1]):
                    v = int(u["verse_ref"].split(".")[2])
                    if u["verse_ref"].rsplit(".", 1)[0] != p["verse_ref"].rsplit(".", 1)[0] or v < rng[0]:
                        break
                    if not u["hindi"]:
                        u["hindi"] = p["hindi"]
                        u["ocr_flags"] = [f for f in u["ocr_flags"] if f != "hindi_missing"] + ["hindi_shared_range"]
        elif m[2] is not None and m[2] != pv:
            p["ocr_flags"].append("hindi_marker_%s_differs_from_sanskrit_%d" % (m[2], pv))

    def handle_block(buf, m):
        exp = S["lastv"] + 1
        if S["expect"] == "H":
            pv = S["lastv"]
            k = tail_run(buf)
            rng = re.findall(r"[०-९0-9]+", m[1])
            same = m[2] is None or m[2] == pv or (len(rng) > 1 and m[2] <= pv)
            if k >= 1 and not (same and m[2] is not None):
                lead = buf[:len(buf) - 1 - k]
                p = S["pend"]; S["pend"] = None
                if lead:
                    p["hindi"] = norm(" ".join(t for _, t in lead))
                    p["source_line_end"] = lead[-1][0]
                    p["ocr_flags"].append("hindi_marker_lost")
                else:
                    p["ocr_flags"].append("hindi_missing")
                S["expect"] = "S"
                handle_block(buf[len(lead):], m)
                return
            finish_pend_with_hindi(buf, m)
            S["expect"] = "S"
            return
        sl, fl = take_S(buf)
        v = m[2]
        flags = sflags() + fl
        if m[0] == "bare":
            flags.append("bare_marker_no_digits")
        rng = re.findall(r"[०-९0-9]+", m[1])
        if len(rng) > 1:
            flags.append("sanskrit_marker_range_" + m[1].translate(DIG))
            v = toint(rng[0])
        if v is None:
            v, conf = exp, "inferred"; flags.append("marker_unreadable_inferred")
        else:
            conf = "explicit"
            if v != exp:
                flags.append("verse_number_nonsequential_expected_%d" % exp)
        S["lastv"] = v
        S["nv"] += 1
        S["pend"] = mk(S["sarga"], v, conf, sl, [(sl[-1][0], "")], flags, [m[1]])
        S["pend"]["hindi"] = ""
        S["expect"] = "H"

    i = start
    while i < end:
        ln = i + 1
        t = norm(lines[i])
        i += 1
        if not t:
            continue
        nl = len(re.findall(r"[\u0904-\u0939\u0958-\u0961]", t))
        if nl == 0 or (nl == 1 and not marker(t)):
            skipped.append((ln, "no-devanagari-noise", t))
            continue
        if HEADING.match(t) and "काण्डे" not in t and "॥" not in t:
            ordw = re.sub(r"[:ः\s|।]|सर्ग", "", t)
            if S["open"] and ordw and "*" not in ordw and ordw == S.get("ordw") and titles:
                skipped.append((ln, "running-header-sarga", t))
                continue
            if S["open"] and not S["interp"] and S["nv"] == 0 and titles and titles[-1]["line"] > ln - 15:
                skipped.append((ln, "duplicate-heading", t))
                continue
            if S["open"] and S["implicit"] and titles and titles[-1]["line"] > ln - 80:
                for u in units:
                    if u["sarga"] == S["sarga"]:
                        u["ocr_flags"] = ["heading_found_after_first_verses" if f == "sarga_heading_missing_inferred" else f
                                          for f in u["ocr_flags"]]
                S["implicit"] = False
                titles[-1]["heading"] = t
                titles[-1]["late_heading_line"] = ln
                S["ordw"] = ordw
                heads += 1
                continue
            if S["open"] or S["buf"]:
                close_sarga()
            S["ordw"] = ordw
            heads += 1
            interp = bool(ordw) and (not re.sub(r"[*१२३४५६७८९0-9]", "", ordw) or ordw.startswith("प्रक्षिप्त"))
            open_sarga(False, interp)
            if interp:
                S["ordw"] = None
                heads -= 1
            titles.append({"sarga": None if interp else S["sarga"], "interpolated_after": S["sarga"] if interp else None, "line": ln, "heading": t, "title": ""})
            continue
        if (t.startswith("इत्या") or t.startswith("इस प्रकार श्रीवाल्मीकि")) and not re.search(
                r"(?<![\u0900-\u097F])सर?्?ग(?![\u0900-\u097F])", t):
            skipped.append((ln, "page-footer-signature", t))
            continue
        if COLOPHON.match(t) or (len(t) < 140 and re.search(r"(?<![\u0900-\u097F])सर?्?ग(?![\u0900-\u097F])\s*(?:पूरा|प्ररा|प्रा|पूर|हुआ|ऊरा)", t)) or "सम्पूर्णम्" in t \
                or t.startswith("इस प्रकार श्रीवाल्मीकि") \
                or (not S["open"] and len(t) < 140 and re.search(r"(?<![\u0900-\u097F])सर?्?ग(?![\u0900-\u097F])", t)):
            if S["open"] or S["buf"]:
                m = COLOPHON_NUM.search(t)
                close_sarga(toint(m.group(1)) if m else None)
            skipped.append((ln, "sarga-colophon", t))
            continue
        if RUNHEAD.search(t) and len(t) < 60:
            skipped.append((ln, "running-header", t))
            continue
        m = marker(t)
        if not S["open"]:
            if m and m[0] == "num":
                open_sarga(True)
                titles.append({"sarga": S["sarga"], "line": ln, "heading": "(missing)", "title": ""})
            else:
                unparsed.append((ln, "outside-sarga: " + t))
                continue
        S["buf"].append((ln, t))
        if m:
            buf = S["buf"]; S["buf"] = []
            handle_block(buf, m)
    if S["open"] or S["buf"]:
        close_sarga()
    return units, unparsed, skipped, titles, heads


def main():
    os.makedirs(OUT, exist_ok=True)
    summary = {}
    vols = {}
    for v in ("vol1", "vol2"):
        with open(os.path.join(RAW, v + ".txt"), encoding="utf-8", errors="replace") as f:
            vols[v] = f.read().split("\n")
    for vol in ("vol1", "vol2"):
        lines = vols[vol]
        starts = find_starts(lines, vol, KANDAS)
        order = sorted((s, k) for k, s in starts.items())
        for idx, (s, key) in enumerate(order):
            e = order[idx + 1][0] if idx + 1 < len(order) else len(lines)
            knum = [k[1] for k in KANDAS if k[0] == key][0]
            units, unp, skp, titles, heads = parse_kanda(lines, s + 1, e, key, knum)
            with open(os.path.join(OUT, key + ".json"), "w", encoding="utf-8") as f:
                json.dump(units, f, ensure_ascii=False, indent=1)
            with open(os.path.join(OUT, key + "_unparsed.txt"), "w", encoding="utf-8") as f:
                for ln, t in unp:
                    f.write("%d\t%s\n" % (ln, t))
            with open(os.path.join(OUT, key + "_skipped.txt"), "w", encoding="utf-8") as f:
                for ln, why, t in skp:
                    f.write("%d\t%s\t%s\n" % (ln, why, t))
            with open(os.path.join(OUT, key + "_titles.json"), "w", encoding="utf-8") as f:
                json.dump(titles, f, ensure_ascii=False, indent=1)
            expl = sum(1 for u in units if u["verse_ref_confidence"] == "explicit")
            flagged = sum(1 for u in units if u["ocr_flags"])
            summary[key] = {"start_line": s + 1, "end_line": e, "sarga_headings": heads,
                            "sargas_in_units": len({u["sarga"] for u in units}),
                            "known_sargas": KNOWN[key], "units": len(units),
                            "explicit": expl, "flagged": flagged, "unparsed_lines": len(unp)}
    with open(os.path.join(OUT, "summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=1)
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
