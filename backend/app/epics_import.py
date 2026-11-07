"""Import unified epic JSON into Postgres.
Usage: python -m backend.app.epics_import [--src DIR] [--epic ramayana|mahabharata|harivamsha] [--dry-run]
Idempotent: one transaction per kanda/parvan, upsert, deletes rows no longer in source.

Key scheme (mahabharata): kanda = parvan 1..18; sarga = CE adhyaya N, or 1000+N for a southern-only adhyaya N;
sarga 0 = unplaced supplement passages of that parvan (rows of kind 'supplement', id 'supp-<NN>-<passage_id>').
Harivamsha: kanda 1..3 = parvan_1..3 (sarga = adhyaya); kanda 0 = 'front' (invocation, adhyaya_000);
kanda 98 = 'unplaced' (source units with no id/adhyaya, sarga 0); kanda 99 = 'appendix_1'
(sarga = appendix adhyaya number, 0 for adhyaya_none). Original verse fields are kept; 'kanda', 'sarga',
'seq_in_sarga', 'layer', 'adhyaya_display' are added."""
import argparse, json, re
from pathlib import Path
from psycopg.types.json import Jsonb
from . import db

KANDAS = {"baala": 1, "ayodhya": 2, "aranya": 3, "kishkindha": 4, "sundara": 5, "yuddha": 6, "uttara": 7}

def _load(p: Path):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        raise SystemExit(f"malformed file {p}: {e}")

def _need(d, p, *keys):
    for k in keys:
        if k not in d: raise SystemExit(f"malformed file {p}: missing '{k}'")

def import_kanda(src: Path, epic: str, key: str, num: int) -> dict:
    kdir = src / key
    sargas, verses = [], []
    for sd in sorted(kdir.glob("sarga_*")):
        if not sd.is_dir(): continue
        sp = sd / "_sarga.json"
        if not sp.exists(): raise SystemExit(f"missing {sp}")
        sdata = _load(sp); _need(sdata, sp, "sarga")
        sn = int(sdata["sarga"])
        sargas.append((epic, num, sn, Jsonb(sdata)))
        for vp in sorted(sd.glob("verse_*.json")):
            d = _load(vp); _need(d, vp, "id", "sarga", "seq_in_sarga", "kanda")
            if d["kanda"].get("number") != num or int(d["sarga"]) != sn:
                raise SystemExit(f"malformed file {vp}: kanda/sarga mismatch with directory")
            verses.append((d["id"], epic, num, sn, int(d["seq_in_sarga"]), d.get("kind"), Jsonb(d)))
    st = {"sargas": [0, 0, 0], "verses": [0, 0, 0]}   # inserted, updated, deleted
    with db.tx() as con:
        con.execute("SET LOCAL synchronous_commit = off")
        for table, rows, keycols, tag in (
                ("epic_sargas", sargas, "epic,kanda,sarga", "sargas"), ("epic_verses", verses, "id", "verses")):
            existing = {}
            for r in con.execute(f"SELECT {keycols.replace(',', '||chr(31)||')} AS k, data FROM {table} WHERE epic=%s AND kanda=%s", (epic, num)):
                existing[r["k"]] = r["data"]
            keyf = (lambda t: f"{t[0]}\x1f{t[1]}\x1f{t[2]}") if tag == "sargas" else (lambda t: t[0])
            new_keys = set()
            todo = []
            for t in rows:
                k = keyf(t); new_keys.add(k)
                if k not in existing: st[tag][0] += 1; todo.append(t)
                elif existing[k] != t[-1].obj: st[tag][1] += 1; todo.append(t)
            if tag == "sargas":
                sql = ("INSERT INTO epic_sargas(epic,kanda,sarga,data) VALUES(%s,%s,%s,%s) "
                       "ON CONFLICT (epic,kanda,sarga) DO UPDATE SET data=EXCLUDED.data")
            else:
                sql = ("INSERT INTO epic_verses(id,epic,kanda,sarga,seq,kind,data) VALUES(%s,%s,%s,%s,%s,%s,%s) "
                       "ON CONFLICT (id) DO UPDATE SET epic=EXCLUDED.epic,kanda=EXCLUDED.kanda,sarga=EXCLUDED.sarga,"
                       "seq=EXCLUDED.seq,kind=EXCLUDED.kind,data=EXCLUDED.data")
            for i in range(0, len(todo), 1000):
                con.cursor().executemany(sql, todo[i:i + 1000])
            gone = [k for k in existing if k not in new_keys]
            st[tag][2] = len(gone)
            if gone:
                if tag == "sargas":
                    for k in gone:
                        e, kn, sn = k.split("\x1f")
                        con.execute("DELETE FROM epic_sargas WHERE epic=%s AND kanda=%s AND sarga=%s", (e, int(kn), int(sn)))
                else:
                    con.cursor().executemany("DELETE FROM epic_verses WHERE id=%s", [(k,) for k in gone])
    return st


# ---------------------------------------------------------------- Mahabharata / Harivamsha

PARVANS = [("adi", "आदिपर्व"), ("sabha", "सभापर्व"), ("aranyaka", "आरण्यकपर्व"), ("virata", "विराटपर्व"),
           ("udyoga", "उद्योगपर्व"), ("bhishma", "भीष्मपर्व"), ("drona", "द्रोणपर्व"), ("karna", "कर्णपर्व"),
           ("shalya", "शल्यपर्व"), ("sauptika", "सौप्तिकपर्व"), ("stri", "स्त्रीपर्व"), ("shanti", "शान्तिपर्व"),
           ("anushasana", "अनुशासनपर्व"), ("ashvamedhika", "आश्वमेधिकपर्व"), ("ashramavasika", "आश्रमवासिकपर्व"),
           ("mausala", "मौसलपर्व"), ("mahaprasthanika", "महाप्रस्थानिकपर्व"), ("svargarohana", "स्वर्गारोहणपर्व")]
MBH = [(i + 1, k, k.capitalize(), sa) for i, (k, sa) in enumerate(PARVANS)]
# (kanda number, folder, name_en, name_sa)
HV = [(1, "parvan_1", "Harivamsha", "हरिवंशपर्व"), (2, "parvan_2", "Vishnu", "विष्णुपर्व"),
      (3, "parvan_3", "Bhavishya", "भविष्यपर्व"), (0, "front", "Front matter (invocation)", "प्रारम्भः"),
      (99, "appendix_1", "Appendix I", "परिशिष्टम् १"), (98, "unplaced", "Unplaced units", "अस्थापितानि")]
HV_LAYER = {"parvan_1": "harivamsha", "parvan_2": "harivamsha", "parvan_3": "harivamsha",
            "front": "front", "appendix_1": "appendix_1", "unplaced": "unplaced"}
BATCH = 500

SQL_SARGA = ("INSERT INTO epic_sargas(epic,kanda,sarga,data) VALUES(%s,%s,%s,%s) ON CONFLICT (epic,kanda,sarga) "
             "DO UPDATE SET data=EXCLUDED.data WHERE epic_sargas.data IS DISTINCT FROM EXCLUDED.data RETURNING (xmax = 0)")
SQL_VERSE = ("INSERT INTO epic_verses(id,epic,kanda,sarga,seq,kind,data) VALUES(%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (id) "
             "DO UPDATE SET epic=EXCLUDED.epic,kanda=EXCLUDED.kanda,sarga=EXCLUDED.sarga,seq=EXCLUDED.seq,"
             "kind=EXCLUDED.kind,data=EXCLUDED.data WHERE epic_verses.data IS DISTINCT FROM EXCLUDED.data "
             "OR epic_verses.kanda<>EXCLUDED.kanda OR epic_verses.sarga<>EXCLUDED.sarga OR epic_verses.seq<>EXCLUDED.seq "
             "RETURNING (xmax = 0)")

def _int(v, p, what):
    try: return int(v)
    except Exception: raise SystemExit(f"malformed file {p}: '{what}' is not an integer ({v!r})")

def _kobj(num, name_sa, name_en, key): return {"number": num, "name_sa": name_sa, "name_en": name_en, "key": key}

def _iter_mbh(src: Path, epic, num, key, name_en, name_sa, seen, cnt):
    """Yield ('sarga', sn, data) and ('verse', id, sn, seq, kind, doc) for one parvan, streaming."""
    kdir = src / key
    kobj = _kobj(num, name_sa, name_en, key)
    dirs = []
    for sd in sorted(kdir.iterdir()):
        if not sd.is_dir(): continue
        m = re.fullmatch(r"(southern_only_)?adhyaya_(\d+)", sd.name)
        if not m: raise SystemExit(f"unexpected directory {sd}")
        n = int(m.group(2)); so = bool(m.group(1))
        dirs.append((1000 + n if so else n, n, so, sd))
    dirs.sort(key=lambda t: t[0])
    for sn, n, so, sd in dirs:
        layer = "southern_only" if so else "critical"
        ap = sd / "_adhyaya.json"
        if not ap.exists(): raise SystemExit(f"missing {ap}")
        a = _load(ap); cnt["sarga_files"] += 1
        if not isinstance(a, dict): raise SystemExit(f"malformed file {ap}: not an object")
        if not so:
            _need(a, ap, "critical_adhyaya")
            if _int(a["critical_adhyaya"], ap, "critical_adhyaya") != n:
                raise SystemExit(f"malformed file {ap}: critical_adhyaya != directory number {n}")
        ch = (a.get("southern_chapters") or [None])[0] or {}
        sdata = dict(a)
        sdata.update(sarga=sn, layer=layer, adhyaya_display=n,
                     title_sa=ch.get("topic") or ch.get("head") or None, title_en=None)
        yield ("sarga", sn, sdata)
        for vp in sorted(sd.glob("verse_*.json")):
            d = _load(vp); cnt["verse_files"] += 1
            _need(d, vp, "id", "seq_in_adhyaya", "parvan")
            if not isinstance(d["parvan"], dict) or d["parvan"].get("number") != num:
                raise SystemExit(f"malformed file {vp}: parvan number mismatch with directory (expected {num})")
            _register(seen, d["id"], vp)
            seq = _int(d["seq_in_adhyaya"], vp, "seq_in_adhyaya")
            d["kanda"] = kobj; d["sarga"] = sn; d["seq_in_sarga"] = seq
            d["layer"] = layer; d["adhyaya_display"] = n
            yield ("verse", d["id"], sn, seq, d.get("kind"), d)

def _iter_mbh_supp(src: Path, epic, num, key, name_en, name_sa, seen, cnt):
    sp = src / "supplements" / f"{num:02d}.json"
    if not sp.exists(): return
    d = _load(sp)
    _need(d, sp, "unplaced_passages")
    if _int(d.get("parvan_number", num), sp, "parvan_number") != num:
        raise SystemExit(f"malformed file {sp}: parvan_number mismatch")
    ps = d["unplaced_passages"]
    cnt["supp_passages"] += len(ps)
    if not ps: return
    cnt["supp_sargas"] += 1
    yield ("sarga", 0, {"sarga": 0, "layer": "supplements_unplaced", "adhyaya_display": 0, "parvan": key,
                        "title_sa": None, "title_en": "Unplaced supplement passages", "passage_count": len(ps),
                        "source_file": f"supplements/{num:02d}.json", "header": d.get("header"),
                        "review_status": "unreviewed", "licence_note": d.get("licence_note")})
    kobj = _kobj(num, name_sa, name_en, key)
    for i, ps_ in enumerate(ps, 1):
        if "passage_id" not in ps_: raise SystemExit(f"malformed file {sp}: passage {i} missing 'passage_id'")
        vid = f"supp-{num:02d}-{ps_['passage_id']}"
        _register(seen, vid, sp)
        doc = {"id": vid, "epic": epic, "kind": "supplement", "kanda": kobj, "sarga": 0, "seq_in_sarga": i,
               "layer": "supplements_unplaced", "adhyaya_display": 0, "passage": ps_,
               "review_status": "unreviewed", "licence_note": d.get("licence_note")}
        yield ("verse", vid, 0, i, "supplement", doc)

def _iter_hv(src: Path, epic, num, folder, name_en, name_sa, seen, cnt):
    kdir = src / folder
    kobj = _kobj(num, name_sa, name_en, folder)
    layer = HV_LAYER[folder]
    dirs = []
    for sd in sorted(kdir.iterdir()):
        if not sd.is_dir(): continue
        m = re.fullmatch(r"adhyaya_(\d+|none)", sd.name)
        if not m: raise SystemExit(f"unexpected directory {sd}")
        n = 0 if m.group(1) == "none" else int(m.group(1))
        dirs.append((n, sd))
    dirs.sort(key=lambda t: (t[0], t[1].name))
    used = set()
    for sn, sd in dirs:
        if sn in used: raise SystemExit(f"duplicate sarga {sn} in {kdir}")
        used.add(sn)
        units = sorted(sd.glob("unit_*.json"))
        cnt["sarga_files"] += 1
        yield ("sarga", sn, {"sarga": sn, "layer": layer, "adhyaya_display": sn, "source_dir": f"{folder}/{sd.name}",
                             "title_sa": None, "title_en": None, "unit_count": len(units),
                             "review_status": "unreviewed"})
        for vp in units:
            d = _load(vp); cnt["verse_files"] += 1
            _need(d, vp, "id", "seq_in_dir")
            _register(seen, d["id"], vp)
            seq = _int(d["seq_in_dir"], vp, "seq_in_dir")
            d["kanda"] = kobj; d["sarga"] = sn; d["seq_in_sarga"] = seq
            d.setdefault("layer", layer); d["adhyaya_display"] = sn
            yield ("verse", d["id"], sn, seq, d.get("kind"), d)

def _register(seen, vid, path):
    if not isinstance(vid, str) or not vid: raise SystemExit(f"malformed file {path}: bad id {vid!r}")
    if vid in seen: raise SystemExit(f"duplicate verse id {vid!r}: {path} and {seen[vid]}")
    seen[vid] = str(path)

def _flush(con, epic, num, buf, stats, tag, sql):
    if not buf: return
    if tag == "verses":
        ids = [r[0] for r in buf]
        for r in con.execute("SELECT id, epic FROM epic_verses WHERE id = ANY(%s) AND epic<>%s", (ids, epic)):
            raise SystemExit(f"verse id {r['id']!r} already exists in another epic ({r['epic']})")
    rows = [(epic, num, *r[1:]) if tag == "sargas" else (r[0], epic, num, *r[1:]) for r in buf]
    cur = con.cursor()
    cur.executemany(sql, rows, returning=True)
    returned = 0
    while True:
        for r in cur.fetchall():
            returned += 1
            stats[tag][0 if next(iter(r.values())) else 1] += 1
        if not cur.nextset(): break
    buf.clear()

def import_parvan(src, epic, gen_fn, num, key, name_en, name_sa, seen, cnt, dry) -> dict:
    """Stream one parvan into the DB in one transaction (or just parse when dry)."""
    stats = {"sargas": [0, 0, 0], "verses": [0, 0, 0], "rows": {"sargas": 0, "verses": 0}}
    gens = [gen_fn(src, epic, num, key, name_en, name_sa, seen, cnt)]
    if gen_fn is _iter_mbh: gens.append(_iter_mbh_supp(src, epic, num, key, name_en, name_sa, seen, cnt))
    sargas_seen, ids_seen, sb, vb = set(), set(), [], []
    ctx = None if dry else db.tx()
    con = ctx.__enter__() if ctx else None
    try:
        if con: con.execute("SET LOCAL synchronous_commit = off")
        for g in gens:
            for item in g:
                if item[0] == "sarga":
                    _, sn, data = item
                    if sn in sargas_seen: raise SystemExit(f"duplicate sarga {sn} in {key}")
                    sargas_seen.add(sn); stats["rows"]["sargas"] += 1
                    sb.append((None, sn, Jsonb(data)))
                    if con and len(sb) >= BATCH: _flush(con, epic, num, sb, stats, "sargas", SQL_SARGA)
                else:
                    _, vid, sn, seq, kind, doc = item
                    ids_seen.add(vid); stats["rows"]["verses"] += 1
                    vb.append((vid, sn, seq, kind, Jsonb(doc)))
                    if con and len(vb) >= BATCH: _flush(con, epic, num, vb, stats, "verses", SQL_VERSE)
        if con:
            _flush(con, epic, num, sb, stats, "sargas", SQL_SARGA)
            _flush(con, epic, num, vb, stats, "verses", SQL_VERSE)
            gone = [r["id"] for r in con.execute("SELECT id FROM epic_verses WHERE epic=%s AND kanda=%s", (epic, num))
                    if r["id"] not in ids_seen]
            for i in range(0, len(gone), 1000):
                con.execute("DELETE FROM epic_verses WHERE id = ANY(%s)", (gone[i:i + 1000],))
            stats["verses"][2] = len(gone)
            gs = [r["sarga"] for r in con.execute("SELECT sarga FROM epic_sargas WHERE epic=%s AND kanda=%s", (epic, num))
                  if r["sarga"] not in sargas_seen]
            for sn in gs:
                con.execute("DELETE FROM epic_sargas WHERE epic=%s AND kanda=%s AND sarga=%s", (epic, num, sn))
            stats["sargas"][2] = len(gs)
    except BaseException as e:
        if ctx: ctx.__exit__(type(e), e, e.__traceback__)
        raise
    else:
        if ctx: ctx.__exit__(None, None, None)
    return stats

def run_big(src, epic, dry=False) -> dict:
    src = Path(src)
    if epic == "harivamsha" and not (src / "parvan_1").is_dir() and (src / "harivamsha" / "parvan_1").is_dir():
        src = src / "harivamsha"   # accept the 'unified' root too
    if epic == "mahabharata": table, gen_fn = MBH, _iter_mbh
    else: table, gen_fn = HV, _iter_hv
    if not dry: db.init()
    total = {"sargas": [0, 0, 0], "verses": [0, 0, 0]}
    rows = {"sargas": 0, "verses": 0}
    seen = {}
    cnt = {"verse_files": 0, "sarga_files": 0, "supp_passages": 0, "supp_sargas": 0}
    for num, key, name_en, name_sa in table:
        if not (src / key).is_dir():
            print(f"{key}: folder missing, skipped"); continue
        st = import_parvan(src, epic, gen_fn, num, key, name_en, name_sa, seen, cnt, dry)
        for t in total:
            for i in range(3): total[t][i] += st[t][i]
        for t in rows: rows[t] += st["rows"][t]
        print(f"{key}: sargas rows {st['rows']['sargas']} +{st['sargas'][0]} ~{st['sargas'][1]} -{st['sargas'][2]}; "
              f"verses rows {st['rows']['verses']} +{st['verses'][0]} ~{st['verses'][1]} -{st['verses'][2]}", flush=True)
    # reconciliation: every verse/unit file and every unplaced supplement passage became a row
    want_v = cnt["verse_files"] + cnt["supp_passages"]
    want_s = cnt["sarga_files"] + cnt["supp_sargas"]
    print(f"reconcile: verse/unit files={cnt['verse_files']} unplaced passages={cnt['supp_passages']} "
          f"adhyaya files={cnt['sarga_files']} (+{cnt['supp_sargas']} supplement sarga-0 rows) -> "
          f"verse rows={rows['verses']} (want {want_v}), sarga rows={rows['sargas']} (want {want_s})")
    if rows["verses"] != want_v or (epic == "mahabharata" and rows["sargas"] != want_s):
        raise SystemExit("reconciliation failed: rows do not match source counts")
    print(f"total: sargas +{total['sargas'][0]} ~{total['sargas'][1]} -{total['sargas'][2]}; "
          f"verses +{total['verses'][0]} ~{total['verses'][1]} -{total['verses'][2]}")
    if dry:
        return {"dry_run": True, "files": cnt["verse_files"] + cnt["sarga_files"], "unplaced_passages": cnt["supp_passages"],
                "sargas": rows["sargas"], "verses": rows["verses"]}
    return total

def run(src, epic="ramayana", dry=False) -> dict:
    if epic in ("mahabharata", "harivamsha"): return run_big(src, epic, dry)
    if dry: raise SystemExit("--dry-run only supported for mahabharata/harivamsha")
    src = Path(src)
    db.init()
    total = {"sargas": [0, 0, 0], "verses": [0, 0, 0]}
    for key, num in KANDAS.items():
        if not (src / key).is_dir(): continue
        st = import_kanda(src, epic, key, num)
        print(f"{key}: sargas +{st['sargas'][0]} ~{st['sargas'][1]} -{st['sargas'][2]}; "
              f"verses +{st['verses'][0]} ~{st['verses'][1]} -{st['verses'][2]}")
        for t in total:
            for i in range(3): total[t][i] += st[t][i]
    print(f"total: sargas +{total['sargas'][0]} ~{total['sargas'][1]} -{total['sargas'][2]}; "
          f"verses +{total['verses'][0]} ~{total['verses'][1]} -{total['verses'][2]}")
    return total

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default="sources/ramayan/unified")
    ap.add_argument("--epic", default="ramayana")
    ap.add_argument("--dry-run", action="store_true", help="parse and validate only, write nothing")
    a = ap.parse_args()
    r = run(a.src, a.epic, a.dry_run)
    if a.dry_run: print(r)
