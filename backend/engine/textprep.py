"""Text frontend helpers (verbatim from the validated CPU renderer, POC/render_cpu.py)."""
def n_aksharas(s):
    """Count syllable nuclei (Devanagari/Kannada): independent vowels + consonants not followed by virama."""
    n = 0; L = len(s)
    for i, c in enumerate(s):
        o = ord(c)
        indep = (0x0905 <= o <= 0x0914) or (0x0C85 <= o <= 0x0C94)
        cons  = (0x0915 <= o <= 0x0939) or (0x0C95 <= o <= 0x0CB9)
        if indep:
            n += 1
        elif cons:
            nxt = s[i+1] if i+1 < L else ""
            if nxt not in ("\u094D", "\u0CCD"):  # not a virama -> carries a vowel
                n += 1
    return n

def _aksharas(s):
    out=[]; cur=""
    for i,c in enumerate(s):
        o=ord(c); base=(0x0C85<=o<=0x0C94) or (0x0905<=o<=0x0914) or (0x0C95<=o<=0x0CB9) or (0x0915<=o<=0x0939)
        prev=s[i-1] if i>0 else ""
        if base and prev not in ("\u0CCD","\u094D"):
            if cur: out.append(cur)
            cur=c
        else: cur+=c
    if cur: out.append(cur)
    return out

def _rep_depths(aks):
    n=len(aks); mono=1; i=0
    while i<n:
        j=i+1
        while j<n and aks[j]==aks[i]: j+=1
        mono=max(mono,j-i); i=j if j>i+1 else i+1
    di=1; i=0
    while i+1<n:
        if aks[i]!=aks[i+1]:
            cnt=1; j=i+2
            while j+1<n and aks[j]==aks[i] and aks[j+1]==aks[i+1]: cnt+=1; j+=2
            di=max(di,cnt); i=j if cnt>1 else i+1
        else: i+=1
    return mono, di

def _resplit_padawise(pieces, max_syll=24):
    out=[]
    for p in pieces:
        words=p.split(); cur=[]; cs=0
        for w in words:
            ws=n_aksharas(w)
            if cur and cs+ws>max_syll: out.append(" ".join(cur)); cur=[w]; cs=ws
            else: cur.append(w); cs+=ws
        if cur: out.append(" ".join(cur))
    return out

_VMATRA = set("ಾಿೀುೂೃೄೆೇೈೊೋೌ")   # Kannada dependent vowel signs
# Visarga half-echo ONLY after a SHORT vowel (i, u, ṛ via matra; inherent short "a" handled in _danda_fix).
# LONG vowels / diphthongs keep the BARE visarga — it elongates the vowel naturally (guṇaiḥ -> "guṇaa-ii-ḥ").
_VECHO_SHORT = {"ಿ": "ಹಿ", "ು": "ಹು", "ೃ": "ಹೃ"}   # short i, u, ṛ -> hi/hu/hṛ
_VLONG = set("ಾೀೂೄೆೇೈೊೋೌ")                          # ā ī ū ṝ e ai o au -> bare visarga
def _danda_fix(s):
    """At a daṇḍa (segment end): anusvara -> m (always). Visarga -> ha/hi/hu echo ONLY after a SHORT vowel
    (inherent a / i / u / ṛ). After a LONG vowel or diphthong (ā/ī/ū/e/ai/o/au) the visarga is kept BARE —
    it elongates the vowel naturally (guṇaiḥ -> "guṇaa-ii-ḥ"), better than a clipped explicit echo. Short i/u
    over-render bare (ಭೀತಿಃ -> "ti-hi-hi") so they get the echo. GLOBAL, every render (disable: --no_danda_fix)."""
    s = s.rstrip()
    if not s: return s
    if s.endswith("ಃ"):
        core = s[:-1]; pv = core[-1] if core else ""
        if pv in _VECHO_SHORT:      # short i/u/ṛ matra -> echo
            s = core + _VECHO_SHORT[pv]
        elif pv in _VLONG:          # long/diphthong matra -> keep bare visarga
            pass
        else:                        # no matra = inherent short "a" -> ha  (namaḥ -> nama-ha)
            s = core + "ಹ"
    elif s.endswith("ಂ"):
        s = s[:-1] + "ಮ್"
    return s

_AN_KA=set("ಕಖಗಘಙ"); _AN_CA=set("ಚಛಜಝಞ"); _AN_TTA=set("ಟಠಡಢಣ"); _AN_TA=set("ತಥದಧನ")
def _anusvara_m(s):
    """Anusvara ಂ -> homorganic nasal of the FOLLOWING consonant (looks past spaces / word boundary):
    ka-varga->ಙ್, ca->ಞ್, ṭa->ಣ್, ta->ನ್; pa-varga & y/r/l/v/ś/ṣ/s/h -> ಮ್. Segment-final ಂ left for
    _danda_fix. Fixes bare-anusvara conjunct drops (तारतम्यं -> ತಾರತಮ್ಯನ್, not "taratan"). Global."""
    res=[]; n=len(s)
    for i,c in enumerate(s):
        if c=="ಂ":
            j=i+1
            while j<n and s[j]==" ": j+=1
            nxt=s[j] if j<n else ""
            if   not nxt:        res.append("ಂ")
            elif nxt in _AN_KA:  res.append("ಙ್")
            elif nxt in _AN_CA:  res.append("ಞ್")
            elif nxt in _AN_TTA: res.append("ಣ್")
            elif nxt in _AN_TA:  res.append("ನ್")
            else:                res.append("ಮ್")
        else: res.append(c)
    return "".join(res)

_SATVA = {"ಚ": "ಶ್", "ಛ": "ಶ್", "ಟ": "ಷ್", "ಠ": "ಷ್", "ತ": "ಸ್", "ಥ": "ಸ್"}  # visarga + c/ch->ś, ṭ/ṭh->ṣ, t/th->s (satva, joined)
def _satva(s):
    """Internal visarga before c/ch, ṭ/ṭh, t/th -> ś/ṣ/s + the consonant (satva, joined conjunct).
    Visarga before ś/ṣ/s, k/kh (jihvāmūlīya), p/ph (upadhmānīya) stays PLAIN -- the model learned those
    acoustically. Segment-final visarga has no following consonant so it is left untouched (for _danda_fix)."""
    out = []; n = len(s); i = 0
    while i < n:
        c = s[i]
        if c == "ಃ":
            j = i + 1
            while j < n and s[j] == " ": j += 1
            nxt = s[j] if j < n else ""
            if nxt in _SATVA:
                out.append(_SATVA[nxt]); i = j; continue   # drop visarga+space, join sibilant to the next akshara
        out.append(c); i += 1
    return "".join(out)

def _hna_metathesis(s):
    """h + retroflex/dental nasal conjunct -> nasal + h (ಹ್ಣ->ಣ್ಹ, ಹ್ನ->ನ್ಹ). F5 struggles with the
    ह्ण/ह्न onset (e.g. गृह्णन्ति); the metathesis is also a legitimate chant pronunciation (breath
    follows the nasal closure). Vowel matra rides along. (disable with --raw)"""
    return s.replace("ಹ್ಣ", "ಣ್ಹ").replace("ಹ್ನ", "ನ್ಹ")

def _vocalic_l(s):
    """Vocalic ḷ/ḹ -> 'lṛ' rendering: ೢ->್ಲೃ, ೣ->್ಲೄ, ಌ->ಲೃ, ೡ->ಲೄ. Rare (√क्लृप्, अचीकॢपत्); model
    renders कॢ like कृ otherwise. Confirmed v043. (disable with --raw)"""
    return s.replace("ೢ", "್ಲೃ").replace("ೣ", "್ಲೄ").replace("ಌ", "ಲೃ").replace("ೡ", "ಲೄ")
