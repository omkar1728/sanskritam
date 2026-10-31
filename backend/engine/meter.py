"""Meter bank + auto-suggestion by syllable count."""
import json
from backend.app import config as C
from . import textprep as T

def load_bank() -> list[dict]:
    bank = json.load(open(C.BANK_JSON, encoding="utf-8"))
    out = []
    for name, e in bank.items():
        if name.startswith("_") or name == "repeat_primes" or not isinstance(e, dict) or "wav" not in e:
            continue
        out.append({"id": e["wav"].replace(".wav", ""), "name": name, "wav": str(C.BANK_JSON.parent / e["wav"]),
                    "ref_text": e["ref_text"], "syllable_count": T.n_aksharas(e["ref_text"]),
                    "sec_per_syll": float(e.get("sec_per_syll", 0.26)), "is_prose": e.get("class") == "gadya"})
    return out

def suggest(padas: list[str], meters: list[dict]) -> dict | None:
    """Nearest bank clip by syllables per segment (same rule as render_production)."""
    from .synth import syllable_counts
    cands = [m for m in meters if not m["is_prose"]]
    if not padas or not cands:
        return None
    counts = syllable_counts(padas)
    first = counts[0]
    best = min(cands, key=lambda m: abs(m["syllable_count"] - first))
    return {"meter_id": best["id"], "meter": best["name"], "syllables_per_segment": counts,
            "reason": f"{' + '.join(map(str, counts))} syllables; closest clip: {best['name']}, "
                      f"{best['syllable_count']} per segment",
            "exact": best["syllable_count"] == first}
