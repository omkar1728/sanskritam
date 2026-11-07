"""Re-run alignment for finished jobs that have none (e.g. rejected by the old strict syllable-count check).

    uv run python -m backend.app.realign            # every done job without an alignment
    uv run python -m backend.app.realign 3 4 5      # just these job ids
Loads MMS_FA (~1.2 GB) in THIS process, one chant at a time; do not run it while a render is in progress.
"""
import json, sys, tempfile
from pathlib import Path
from . import db, queue, storage, verses


def realign(jid: int) -> str:
    j = db.q1("SELECT * FROM jobs WHERE id=?", (jid,))
    a = db.q1("SELECT * FROM assets WHERE job_id=?", (jid,))
    if not j or not a or not a["wav_key"]: return "skip (no job/wav)"
    v = verses.present(db.q1("SELECT * FROM verses WHERE id=?", (j["verse_id"],)))
    st = storage.get()
    with tempfile.TemporaryDirectory() as td:
        wd = Path(td); wav = wd / "chant.wav"
        st.download(a["wav_key"], str(wav))
        path = queue._align(jid, str(wav), verses.padas(v["text"]), wd)
        if not path: return "still unaligned (see job log)"
        ak = queue.key(jid, "alignment.json")
        st.put_file(ak, path, "application/json")
    db.x("UPDATE assets SET alignment_key=? WHERE job_id=?", (ak, jid))
    return "aligned"

def main(argv):
    ids = [int(x) for x in argv] or [r["job_id"] for r in db.q(
        "SELECT a.job_id FROM assets a JOIN jobs j ON j.id=a.job_id WHERE a.alignment_key IS NULL AND j.status='done' ORDER BY a.job_id")]
    print(f"{len(ids)} job(s)", flush=True)
    try:
        for i in ids: print(i, realign(i), flush=True)    # model loads once, stays loaded for the whole run
    finally:
        queue.release_aligner()

if __name__ == "__main__": main(sys.argv[1:])
