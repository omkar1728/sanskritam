"""Word/syllable alignment: MMS_FA (torchaudio, CTC, romanised chars) forced alignment of the generated WAV.

SLP1 (from Vāgdhenu's align_slp1) -> latin letters the MMS dictionary knows -> forced_align ->
per-character times -> syllables (tts_syllabify) -> words. Output is validated; on failure the caller
falls back to line-level timing.
"""
from __future__ import annotations
import sys
from backend.app import config as C

# SLP1 char -> MMS romanisation (MMS dictionary: a-z and ')
_ROM = {
    "a": "a", "A": "a", "i": "i", "I": "i", "u": "u", "U": "u", "f": "ri", "F": "ri", "x": "li", "X": "li",
    "e": "e", "E": "ai", "o": "o", "O": "au", "M": "m", "H": "h",
    "k": "k", "K": "kh", "g": "g", "G": "gh", "N": "n", "c": "ch", "C": "chh", "j": "j", "J": "jh", "Y": "n",
    "w": "t", "W": "th", "q": "d", "Q": "dh", "R": "n", "t": "t", "T": "th", "d": "d", "D": "dh", "n": "n",
    "p": "p", "P": "ph", "b": "b", "B": "bh", "m": "m", "y": "y", "r": "r", "l": "l", "v": "v",
    "S": "sh", "z": "sh", "s": "s", "h": "h",
}
HOP_S = 0.02          # MMS_FA frame = 20 ms
_model = None

def _get_model(device="cpu"):
    global _model
    if _model is None:
        import torchaudio
        b = torchaudio.pipelines.MMS_FA
        _model = (b.get_model(with_star=False).to(device).eval(), b.get_dict(star=None), b.sample_rate)
    return _model

def unload():
    global _model
    _model = None

def _slp1_words(padas: list[str]):
    if str(C.SRC) not in sys.path:
        sys.path.insert(0, str(C.SRC))
    import prep_text as PT, tts_syllabify as S
    words = []                    # [(line_idx, slp1_word, [syllable_text...])]
    for li, p in enumerate(padas):
        for w in PT.align_slp1(p).split(" "):
            if not w: continue
            syl = [s["text"] for s in S.syllabify(w)]
            if "".join(syl).replace("~", "") != w.replace("~", ""):
                raise ValueError(f"syllabification mismatch for {w!r}: {syl}")
            words.append((li, w, syl))
    return words

def align(wav_path: str, padas: list[str], display_words: list[list[str]] | None = None, device="cpu") -> dict:
    """display_words: per line, the Devanagari words (to show in the UI); must match the SLP1 word count."""
    import torch, torchaudio
    from torchaudio.functional import forced_align, merge_tokens
    model, dic, sr = _get_model(device)
    wav, wsr = torchaudio.load(wav_path)
    wav = wav.mean(0, keepdim=True)
    if wsr != sr: wav = torchaudio.functional.resample(wav, wsr, sr)
    dur = wav.shape[1] / sr

    words = _slp1_words(padas)
    # token list: one entry per latin letter, remembering its (word, syllable, char) owner
    toks, owner = [], []
    for wi, (_, w, syl) in enumerate(words):
        ci = 0
        for si, st in enumerate(syl):
            for ch in st:
                if ch == "~": continue
                for letter in _ROM.get(ch, ""):
                    toks.append(dic[letter]); owner.append((wi, si, ci))
                ci += 1
    with torch.inference_mode():
        emis, _ = model(wav.to(device))
        emis = torch.log_softmax(emis, -1).cpu()
    ali, _ = forced_align(emis, torch.tensor([toks], dtype=torch.int32), blank=0)
    spans = merge_tokens(ali[0], torch.exp(emis[0].gather(1, ali[0][:, None]).squeeze(1)))
    if len(spans) != len(toks):
        raise RuntimeError(f"aligned {len(spans)} tokens, expected {len(toks)}")

    # per syllable: first letter start .. last letter end (seconds)
    syl_t = {}
    for sp, (wi, si, _) in zip(spans, owner):
        a, b = sp.start * HOP_S, sp.end * HOP_S
        lo, hi = syl_t.get((wi, si), (a, b)); syl_t[(wi, si)] = (min(lo, a), max(hi, b))

    out_words = []
    for wi, (li, w, syl) in enumerate(words):
        starts = [syl_t[(wi, si)][0] for si in range(len(syl))]
        nxt_word_start = syl_t[(wi + 1, 0)][0] if wi + 1 < len(words) else dur
        last_end = syl_t[(wi, len(syl) - 1)][1]
        # CTC peaks sit near the onset: let the last syllable ring until the next word, capped
        w_end = min(nxt_word_start, last_end + 0.35)
        sylls = []
        for si, st in enumerate(syl):
            e = starts[si + 1] if si + 1 < len(syl) else w_end
            sylls.append({"slp1": st, "start": round(starts[si], 3), "end": round(e, 3)})
        out_words.append({"line": li, "slp1": w, "start": round(starts[0], 3), "end": round(w_end, 3), "syllables": sylls})

    lines = []
    for li in range(len(padas)):
        ws = [w for w in out_words if w["line"] == li]
        if display_words:
            if len(display_words[li]) != len(ws): raise ValueError("display word count mismatch on line %d" % li)
            for d, w in zip(display_words[li], ws): w["text"] = d
        for w in ws: w.setdefault("text", w["slp1"])
        lines.append({"words": ws})
    return {"audio_duration": round(dur, 3), "lines": lines}

def validate(al: dict, expected_syllables: list[int] | None = None) -> list[str]:
    """Return a list of problems (empty = OK)."""
    errs, prev = [], -1.0
    for li, ln in enumerate(al["lines"]):
        n = 0
        for w in ln["words"]:
            for s in w["syllables"]:
                n += 1
                if s["start"] < prev - 1e-6: errs.append(f"non-monotonic at {s['slp1']} ({s['start']} < {prev})")
                if s["end"] < s["start"]: errs.append(f"negative span at {s['slp1']}")
                if s["end"] > al["audio_duration"] + 0.05: errs.append(f"beyond audio at {s['slp1']}")
                prev = s["start"]
        if expected_syllables and n != expected_syllables[li]:
            errs.append(f"line {li}: {n} syllables, expected {expected_syllables[li]}")
    return errs


def shift(al: dict, offset_s: float, new_duration: float) -> dict:
    """Move all times by `offset_s` (the MP3 has a lead-in the WAV does not) and set the new total duration."""
    for ln in al["lines"]:
        for w in ln["words"]:
            w["start"] = round(w["start"] + offset_s, 3); w["end"] = round(w["end"] + offset_s, 3)
            for s in w["syllables"]:
                s["start"] = round(s["start"] + offset_s, 3); s["end"] = round(s["end"] + offset_s, 3)
    al["audio_duration"] = round(new_duration, 3)
    return al
