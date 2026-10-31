"""Generate render_cpu.py: a CPU port of Vagdhenu's src/render_production.py.

Only paths and device handling change; the synthesis logic is copied as-is.
Usage: uv run python port_renderer.py
"""
import os

HERE = os.path.dirname(os.path.abspath(__file__))
VAG = os.path.join(HERE, "EdgeSanskrit-TTS", "vagdhenu")
BIGVGAN = os.path.join(HERE, "EdgeSanskrit-TTS", "BigVGAN")

src = open(os.path.join(VAG, "src", "render_production.py"), encoding="utf-8").read()


def sub(old, new, count=1):
    global src
    assert src.count(old) == count, f"expected {count}x {old!r}, found {src.count(old)}"
    src = src.replace(old, new)


sub('PROD = "<PROD>"\nsys.path.insert(0, PROD)',
    f'PROD = {os.path.join(VAG, "src")!r}\nsys.path.insert(0, PROD)\nsys.path.insert(0, {BIGVGAN!r})')
sub('CHAMP = f"{PROD}/CHAMPION_2026-06-11"', f'CHAMP = {os.path.join(VAG, "models")!r}')
sub('f"{PROD}/production/reference_bank/bank.json"', f'{os.path.join(VAG, "src", "reference_bank", "bank.json")!r}')
sub('vocab = glob.glob(os.path.expanduser("~/.cache/huggingface/hub/models--ai4bharat--IndicF5/snapshots/*/checkpoints/vocab.txt"))[0]',
    f'vocab = {os.path.join(VAG, "models", "vocab.txt")!r}')
sub('device="cuda"', 'device="cpu"', count=2)
sub('torch.load(a.voice, map_location="cpu", weights_only=True)',
    'torch.load(a.voice, map_location="cpu", weights_only=True, mmap=True)')
sub('cfm.load_state_dict(ema, strict=False); cfm.eval()',
    'cfm.load_state_dict(ema, strict=False); cfm.eval(); del ck, ema')
sub('g = bigvgan.BigVGAN.from_pretrained("nvidia/bigvgan_v2_24khz_100band_256x", use_cuda_kernel=False)',
    'g = bigvgan.BigVGAN(bigvgan.load_hparams_from_json(' + repr(os.path.join(BIGVGAN, "configs", "bigvgan_v2_24khz_100band_256x.json")) + '), use_cuda_kernel=False)')
sub('g = g.cuda().eval()', 'g = g.eval()')
sub('torch.from_numpy(mel).cuda()', 'torch.from_numpy(mel)')
sub('    y = bvgan(cap.last); mx = np.abs(y).max()',
    '    np.save(f"{a.out}.mel{i}.npy", cap.last)  # kept so the mel can be time-stretched and re-vocoded later\n    y = bvgan(cap.last); mx = np.abs(y).max()')
assert "cuda" not in src.replace("use_cuda_kernel", ""), "leftover cuda reference"

out = os.path.join(HERE, "render_cpu.py")
open(out, "w", encoding="utf-8").write(src)
print("wrote", out)
