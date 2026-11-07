"""Snapshot read-only backend API into static JSON files (GET only)."""
import argparse, json, os, urllib.request, urllib.error, urllib.parse

ap = argparse.ArgumentParser()
ap.add_argument("--base", default="http://127.0.0.1:8001")
ap.add_argument("--out", default="Android/staticdata")
a = ap.parse_args()
base = a.base.rstrip("/")
counts = {}
total = 0


def get(path):
    try:
        with urllib.request.urlopen(base + "/api/" + path) as r:
            return r.read()
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise


def q(x):
    return urllib.parse.quote(str(x), safe="")


def save(rel, data, kind):
    global total
    p = os.path.join(a.out, rel)
    os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
    if not isinstance(data, bytes):
        data = json.dumps(data, ensure_ascii=False).encode()
    with open(p, "wb") as f:
        f.write(data)
    total += len(data)
    counts[kind] = counts.get(kind, 0) + 1


def getj(path):
    b = get(path)
    return None if b is None else json.loads(b)


for n in ("meters", "voices", "settings", "executors"):
    d = getj(n)
    save(n + ".json", d if d is not None else ([] if n != "settings" else {}), n)

verses = getj("verses") or []
save("verses.json", verses, "verses.json")
for v in verses:
    d = getj("verses/" + q(v["id"]))
    if d is not None:
        save(f"verses/{v['id']}.json", d, "verse")

# /api/jobs only lists the latest 100 (incl. unfinished ones), so take every job that has audio from the verses too
jobs = [j for j in (getj("jobs") or []) if j.get("status") == "done"]
seen = {j["id"] for j in jobs}
for v in verses:
    for au in v.get("audio") or []:
        if au["job_id"] not in seen:
            seen.add(au["job_id"])
            jobs.append({"id": au["job_id"], "verse_id": v["id"], "meter_id": au.get("meter_id"), "voice_id": au.get("voice_id"),
                         "steps": au.get("steps"), "status": "done", "progress": 1.0, "error": None})
jobs.sort(key=lambda j: -j["id"])
save("jobs.json", jobs, "jobs.json")
for j in jobs:
    i = j["id"]
    d = getj("jobs/" + q(i))
    if d is None:
        continue
    save(f"jobs/{i}.json", d, "job")
    al = getj(f"jobs/{q(i)}/alignment")
    if al is not None:
        save(f"jobs/{i}/alignment.json", al, "alignment")
    au = get(f"jobs/{q(i)}/audio.mp3")
    if au is not None:
        save(f"jobs/{i}/audio.mp3", au, "audio")

epics = [e for e in (getj("epics") or []) if e["id"] == "ramayana"]
save("epics.json", epics, "epics.json")
kandas = [k for k in (getj("epics/ramayana/kandas") or []) if k["number"] == 1]
save("epics/ramayana/kandas.json", kandas, "kandas.json")
sargas = getj("epics/ramayana/kandas/1/sargas") or []
save("epics/ramayana/kandas/1/sargas.json", sargas, "sargas.json")
for s in sargas:
    d = getj(f"epics/ramayana/kandas/1/sargas/{s['sarga']}")
    if d is not None:
        save(f"epics/ramayana/kandas/1/sargas/{s['sarga']}.json", d, "sarga")

print(counts)
print(f"total {total/1e6:.2f} MB")
