"""A syllable-COUNT mismatch keeps the alignment (flagged); timing errors still reject it. Fake aligner, no model."""
import json
from pathlib import Path
from backend.app import queue
from backend.engine import align as A

def _al(start2=0.5):
    syl = lambda t, a, b: {"slp1": t, "start": a, "end": b}
    return {"audio_duration": 2.0, "lines": [{"words": [{"line": 0, "slp1": "ka", "text": "क", "start": 0.0, "end": 1.0,
            "syllables": [syl("ka", 0.0, 0.5), syl("ka", start2, 1.0)]}]}]}

def _run(monkeypatch, tmp_path, al):
    monkeypatch.setattr(A, "align", lambda *a, **k: al)
    monkeypatch.setattr(A, "unload", lambda: None)
    monkeypatch.setattr("backend.engine.synth.syllable_counts", lambda p: [3])   # FIXTURE: text counter says 3, aligner has 2
    return queue._align(1, "x.wav", ["क"], tmp_path)

def test_count_mismatch_kept(monkeypatch, tmp_path):
    p = _run(monkeypatch, tmp_path, _al())
    assert p and "syllable_count_note" in json.loads(Path(p).read_text())

def test_timing_error_rejected(monkeypatch, tmp_path):
    assert _run(monkeypatch, tmp_path, _al(start2=-1.0)) is None
