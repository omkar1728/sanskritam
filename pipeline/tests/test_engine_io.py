"""engine_io with the FakeEngine (no models). All verse text here is FIXTURE text, not real verses."""
from types import SimpleNamespace

import pytest

from pipeline import engine_io as E

PADAS = ["FIXTURE pada one", "FIXTURE pada two"]


@pytest.fixture(autouse=True)
def fake_mode(monkeypatch):
    monkeypatch.setenv("PIPELINE_FAKE", "1")
    monkeypatch.delenv("PIPELINE_FAKE_ALIGN_FAIL", raising=False)


def _render(tmp_path):
    rec = SimpleNamespace(padas=PADAS, verse_id="fixture-001-001")
    spec = E.build_render_spec({"steps": 10, "seed": 50, "meter": "anuṣṭubh"}, rec, str(tmp_path / "a.wav"), "cpu")
    assert spec.out_wav.endswith("a.wav")
    return E.FakeEngine().render(spec)


def test_fake_render_copies_wav(tmp_path):
    res = _render(tmp_path)
    assert (tmp_path / "a.wav").stat().st_size > 1000
    assert res["duration"] > 1 and len(res["syllables"]) == 2


def test_fake_render_failure_hook(tmp_path):
    spec = E.FakeSpec(padas=["FIXTURE RENDERFAIL"], out_wav=str(tmp_path / "x.wav"))
    with pytest.raises(RuntimeError):
        E.FakeEngine().render(spec)


def test_align_ok_is_shifted_by_lead(tmp_path):
    res = _render(tmp_path)
    al, err = E.align_with_retries(res["wav"], PADAS, retries=2)
    assert err is None and al is not None
    first = al["lines"][0]["words"][0]
    assert first["start"] == pytest.approx(E.LEAD_MS / 1000, abs=0.01)       # fake aligner starts at 0
    assert al["audio_duration"] == pytest.approx(res["duration"] + E.LEAD_MS / 1000 + E.TAIL_S, abs=0.01)
    assert E.align_with_retries.last_attempts == 1


def test_align_retries_then_fails(tmp_path):
    res = _render(tmp_path)
    calls = []

    def bad(wav, padas, display_words=None):
        calls.append(1)
        raise RuntimeError("boom")

    al, err = E.align_with_retries(res["wav"], PADAS, retries=2, aligner=bad)
    assert al is None and "boom" in err
    assert len(calls) == 3                      # 1 try + 2 retries


def test_align_retry_succeeds_second_time(tmp_path):
    res = _render(tmp_path)
    n = {"c": 0}

    def flaky(wav, padas, display_words=None):
        n["c"] += 1
        if n["c"] == 1:
            raise RuntimeError("transient")
        return E.fake_align(wav, padas)

    al, err = E.align_with_retries(res["wav"], PADAS, retries=2, aligner=flaky)
    assert al is not None and err is None and n["c"] == 2


def test_validation_errors_are_retried(tmp_path):
    res = _render(tmp_path)
    n = {"c": 0}

    def non_monotonic(wav, padas, display_words=None):
        n["c"] += 1
        al = E.fake_align(wav, padas)
        al["lines"][0]["words"][0]["syllables"][0]["start"] = 99.0         # beyond/non-monotonic
        return al

    al, err = E.align_with_retries(res["wav"], PADAS, retries=1, aligner=non_monotonic)
    assert al is None and "rejected" in err and n["c"] == 2


def test_valueerror_falls_back_to_slp1_words(tmp_path):
    res = _render(tmp_path)
    seen = []

    def picky(wav, padas, display_words=None):
        seen.append(display_words)
        if display_words:
            raise ValueError("display word count mismatch on line 0")
        return E.fake_align(wav, padas)

    al, err = E.align_with_retries(res["wav"], PADAS, retries=0, aligner=picky)
    assert al is not None and seen[0] is not None and seen[1] is None


def test_encode_mp3_creates_file(tmp_path):
    res = _render(tmp_path)
    out = tmp_path / "a.mp3"
    E.encode_mp3(res["wav"], str(out), 96)
    assert out.stat().st_size > 100


def test_unknown_meter_errors_clearly(monkeypatch):
    monkeypatch.delenv("PIPELINE_FAKE")
    monkeypatch.setattr(E, "_BANK_CACHE", [{"name": "anuṣṭubh"}])
    with pytest.raises(ValueError, match="unknown meter"):
        E.find_meter("no-such-meter")


class FakeStore:
    def __init__(self, blobs):
        self.blobs = blobs

    def read_range(self, rel, off, length):
        return self.blobs[rel][off:off + length]


def test_read_old_blob_by_offsets():
    store = FakeStore({"segments/seg-r-w0-0000.wav.pack": b"AAAAWAVBBB", "segments/seg-r-w0-0000.audio.pack": b"xxMP3yy"})
    entry = {"segment": "seg-r-w0-0000", "wav": {"off": 4, "len": 3}, "audio": {"off": 2, "len": 3}}
    assert E.read_old_blob(store, entry, "wav") == b"WAV"
    assert E.read_old_blob(store, entry, "audio") == b"MP3"
    assert E.ref_off_len([5, 6]) == (5, 6)


def test_count_syllables_fake():
    assert E.count_syllables(["ab cd", "e"]) == 5
