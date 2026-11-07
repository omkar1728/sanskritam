"""Colab batch mode tests: fake render only (no torch, models or GPU)."""
import ast, json, os, subprocess, sys
from pathlib import Path
import pytest
from backend.executors.bundle import resolve_spec_dict
from backend.worker import colab_worker as cw
from backend.worker.colab_worker import run_batch

ROOT = Path(__file__).resolve().parents[2]


def mk_batch(d: Path, ids, bad_path=False):
    (d / "refs").mkdir(parents=True)
    (d / "refs" / "anushtubh.wav").write_bytes(b"x")
    jobs = []
    for i in ids:
        spec = dict(padas=["a"], ref_wav="refs/anushtubh.wav", ref_text="t", sec_per_syll=0.5,
                    voice_ckpt="models/v.pt", vocoder_ckpt="models/b.pth", out_wav="ignored.wav", steps=8, seed=1, device="cpu")
        if bad_path and i == ids[0]: spec["ref_wav"] = "../evil.wav"
        jobs.append(dict(job_id=i, verse_id=i * 10, spec=spec))
    (d / "batch.json").write_text(json.dumps(dict(version=1, batch_id="b", jobs=jobs)))


def mk_root_batch(d: Path, ids, bad=None):
    mk_batch(d, ids)
    meta = json.loads((d / "batch.json").read_text())
    meta.update(results_root="batch_results", batch_dir="batch_results/_batches/b")
    for j in meta["jobs"]:
        j["result_dir"] = f"batch_results/epic/kanda/sarga_001/v-{j['job_id']:03d}"
    if bad is not None: meta["jobs"][0]["result_dir"] = bad
    (d / "batch.json").write_text(json.dumps(meta))


def fake_render(calls=None, fail=()):
    def render(spec, progress):
        progress(1, 2, "half")
        if calls is not None: calls.append(spec)
        if Path(spec["out_wav"]).parent.name in {str(f) for f in fail}: raise RuntimeError("boom")
        Path(spec["out_wav"]).write_bytes(b"RIFF")
        return {"duration": 1.5, "pada_spans": [[0, 1.5]], "syllables": []}
    return render


def test_happy_path(tmp_path, capsys):
    mk_batch(tmp_path / "b", [1, 2, 3])
    calls = []
    s = run_batch(tmp_path / "b", tmp_path / "r", tmp_path / "m", fake_render(calls))
    assert s == dict(ok=3, skipped=0, failed=0, total=3)
    for i in (1, 2, 3):
        assert (tmp_path / "r" / str(i) / "chant.wav").exists()
        assert json.loads((tmp_path / "r" / str(i) / "result.json").read_text())["duration"] == 1.5
    assert not (tmp_path / "r" / "errors.json").exists()
    assert calls[0]["out_wav"].startswith(str(tmp_path / "r" / "1"))   # atomic: partial name, renamed after
    assert calls[0]["voice_ckpt"] == str(tmp_path / "m" / "v.pt")
    out = capsys.readouterr().out
    assert "[batch] 3/3 job 3 ok" in out and "PROGRESS" in out


def test_resume_skips_done(tmp_path):
    mk_batch(tmp_path / "b", [1, 2])
    run_batch(tmp_path / "b", tmp_path / "r", tmp_path / "m", fake_render())
    (tmp_path / "r" / "2" / "result.json").unlink()
    calls = []
    s = run_batch(tmp_path / "b", tmp_path / "r", tmp_path / "m", fake_render(calls))
    assert s["skipped"] == 1 and s["ok"] == 1 and len(calls) == 1


def test_failure_recorded_others_complete(tmp_path):
    mk_batch(tmp_path / "b", [1, 2, 3])
    s = run_batch(tmp_path / "b", tmp_path / "r", tmp_path / "m", fake_render(fail=[2]))
    assert s["ok"] == 2 and s["failed"] == 1
    errs = json.loads((tmp_path / "r" / "errors.json").read_text())
    assert list(errs) == ["2"] and "boom" in errs["2"]
    assert (tmp_path / "r" / "3" / "chant.wav").exists()
    # rerun succeeds -> error cleared
    s = run_batch(tmp_path / "b", tmp_path / "r", tmp_path / "m", fake_render())
    assert s["ok"] == 1 and json.loads((tmp_path / "r" / "errors.json").read_text()) == {}


def test_unsafe_path_rejected_in_batch(tmp_path):
    mk_batch(tmp_path / "b", [1, 2], bad_path=True)
    s = run_batch(tmp_path / "b", tmp_path / "r", tmp_path / "m", fake_render())
    assert s["failed"] == 1 and s["ok"] == 1
    assert "unsafe" in json.loads((tmp_path / "r" / "errors.json").read_text())["1"]


def test_resolve_spec_dict(tmp_path):
    spec = dict(ref_wav="refs/x.wav", voice_ckpt="models/v.pt", vocoder_ckpt="models/b.pth")
    r = resolve_spec_dict(spec, tmp_path / "base", tmp_path / "mod")
    assert r["ref_wav"] == str(tmp_path / "base" / "refs" / "x.wav")
    assert r["voice_ckpt"] == str(tmp_path / "mod" / "v.pt")
    assert "out_wav" not in r and "out_wav" not in spec
    for k, v in [("ref_wav", "/etc/passwd"), ("voice_ckpt", "models/../../x"), ("vocoder_ckpt", "..\\x")]:
        with pytest.raises(ValueError):
            resolve_spec_dict(dict(spec, **{k: v}), tmp_path, tmp_path)


def test_notebook_valid():
    nb = json.loads((ROOT / "notebooks" / "colab_batch.ipynb").read_text(encoding="utf-8"))
    assert nb["nbformat"] == 4
    code = [c for c in nb["cells"] if c["cell_type"] == "code"]
    assert len(code) == 1
    src = "".join(code[0]["source"])
    assert not any(l.lstrip().startswith(("!", "%")) for l in src.splitlines())
    ast.parse(src)
    assert "DRIVE_FOLDER" in src and "files.upload()" in src
    assert "WORKERS" in src and "--workers" in src and "--results-root" in src
    assert "DOWNLOAD_ZIP = False" in src and "#@param {type:\"boolean\"}" in src


@pytest.mark.parametrize("n", [1, 2, 3, 4])
def test_shards_cover_every_job_once(n):
    jobs = [dict(job_id=i) for i in range(10)]
    seen = []
    for i in range(n):
        part = cw.shard_jobs(jobs, (i, n))
        assert all((idx - 1) % n == i for idx, _ in part)
        seen += [j["job_id"] for _, j in part]
    assert sorted(seen) == list(range(10))


def test_parse_shard():
    assert cw.parse_shard("1/3") == (1, 3)
    for bad in ("3/3", "x", "-1/2", "0/0"):
        with pytest.raises(ValueError): cw.parse_shard(bad)


def test_sharded_run_and_merge_errors(tmp_path):
    mk_batch(tmp_path / "b", [1, 2, 3, 4])
    r = tmp_path / "r"
    s0 = run_batch(tmp_path / "b", r, tmp_path / "m", fake_render(fail=[3]), shard=(0, 2))
    s1 = run_batch(tmp_path / "b", r, tmp_path / "m", fake_render(fail=[2]), shard=(1, 2))
    assert s0["total"] == 2 and s1["total"] == 2 and s0["failed"] == 1 and s1["failed"] == 1
    assert json.loads((r / "errors.0.json").read_text()).keys() == {"3"}
    assert not (r / "errors.json").exists()
    # job 2 later gets a result (e.g. from another run): merge drops it
    (r / "2").mkdir(exist_ok=True); (r / "2" / "chant.wav").write_bytes(b"x"); (r / "2" / "result.json").write_text("{}")
    merged = cw.merge_errors(r)
    assert list(merged) == ["3"] and json.loads((r / "errors.json").read_text()).keys() == {"3"}
    assert not list(r.glob("errors.*.json"))


def test_resume_across_shards(tmp_path):
    mk_batch(tmp_path / "b", [1, 2, 3, 4])
    r = tmp_path / "r"
    for i in range(2): run_batch(tmp_path / "b", r, tmp_path / "m", fake_render(), shard=(i, 2))
    calls = []
    for i in range(2):
        s = run_batch(tmp_path / "b", r, tmp_path / "m", fake_render(calls), shard=(i, 2))
        assert s["skipped"] == 2 and s["ok"] == 0
    assert calls == []


def test_resource_warnings():
    assert cw.resource_warnings(1, avail_gb=8, cpus=2) == []
    w = cw.resource_warnings(3, avail_gb=8.0, cpus=2)
    assert len(w) == 2
    assert "WARNING" in w[0] and "10.8 GB" in w[0] and "8.0 GB" in w[0]
    assert "3 workers" in w[1] and "2 CPU" in w[1]
    assert cw.GB_PER_WORKER == 3.6


def test_multiprocess_fake_render(tmp_path):
    ids = list(range(1, 7))
    mk_batch(tmp_path / "b", ids)
    r = tmp_path / "r"
    (r).mkdir()
    (r / "errors.json").write_text(json.dumps({"1": "old"}))
    env = dict(os.environ, SS_FAKE_RENDER="1")   # test hook: fake render, no torch
    p = subprocess.run([sys.executable, "-u", "-m", "backend.worker.colab_worker", "--batch", str(tmp_path / "b"),
                        "--results", str(r), "--models-dir", str(tmp_path / "m"), "--workers", "2"],
                       cwd=ROOT, env=env, capture_output=True, text=True, timeout=120)
    assert p.returncode == 0, p.stdout + p.stderr
    for i in ids:
        assert (r / str(i) / "chant.wav").exists() and (r / str(i) / "result.json").exists()
    assert "[w0]" in p.stdout and "[w1]" in p.stdout
    assert json.loads((r / "errors.json").read_text()) == {}
    assert not list(r.glob("errors.*.json"))


def test_root_layout_paths(tmp_path):
    mk_root_batch(tmp_path / "b", [1, 2])
    root = tmp_path / "drive"
    s = run_batch(tmp_path / "b", None, tmp_path / "m", fake_render(), results_root=root)
    assert s["ok"] == 2
    for i in (1, 2):
        d = root / "batch_results/epic/kanda/sarga_001" / f"v-{i:03d}"
        assert (d / "chant.wav").exists() and json.loads((d / "result.json").read_text())["duration"] == 1.5
        assert not (d / "chant.part.wav").exists()


def test_root_resume_marker_is_result_json(tmp_path):
    mk_root_batch(tmp_path / "b", [1, 2])
    root = tmp_path / "drive"
    d1 = root / "batch_results/epic/kanda/sarga_001/v-001"
    d1.mkdir(parents=True); (d1 / "chant.wav").write_bytes(b"half")     # wav only: NOT done
    d2 = root / "batch_results/epic/kanda/sarga_001/v-002"
    d2.mkdir(parents=True); (d2 / "chant.wav").write_bytes(b"x"); (d2 / "result.json").write_text("{}")
    calls = []
    s = run_batch(tmp_path / "b", None, tmp_path / "m", fake_render(calls), results_root=root)
    assert s["ok"] == 1 and s["skipped"] == 1 and len(calls) == 1
    assert (d1 / "chant.wav").read_bytes() == b"RIFF" and (d1 / "result.json").exists()


@pytest.mark.parametrize("bad", ["/abs/x", "batch_results/../x", "a\\b", "C:/x", "", "a//b"])
def test_unsafe_result_dir_rejected(tmp_path, bad):
    mk_root_batch(tmp_path / "b", [1, 2], bad=bad)
    with pytest.raises(ValueError):
        run_batch(tmp_path / "b", None, tmp_path / "m", fake_render(), results_root=tmp_path / "drive")
    assert not (tmp_path / "drive").exists()


def test_unsafe_batch_dir_rejected(tmp_path):
    mk_root_batch(tmp_path / "b", [1])
    meta = json.loads((tmp_path / "b" / "batch.json").read_text()); meta["batch_dir"] = "../x"
    (tmp_path / "b" / "batch.json").write_text(json.dumps(meta))
    with pytest.raises(ValueError):
        run_batch(tmp_path / "b", None, tmp_path / "m", fake_render(), results_root=tmp_path / "drive")


def test_root_errors_location_and_merge(tmp_path):
    mk_root_batch(tmp_path / "b", [1, 2, 3, 4])
    root = tmp_path / "drive"
    run_batch(tmp_path / "b", None, tmp_path / "m", fake_render(fail=["v-003"]), shard=(0, 2), results_root=root)
    run_batch(tmp_path / "b", None, tmp_path / "m", fake_render(fail=["v-002"]), shard=(1, 2), results_root=root)
    ed = root / "batch_results/_batches/b"
    assert json.loads((ed / "errors.0.json").read_text()).keys() == {"3"}
    _, dirs, err_dir = cw.load_layout(tmp_path / "b", None, root)
    assert err_dir == ed
    d2 = dirs["2"]; d2.mkdir(parents=True, exist_ok=True)
    (d2 / "chant.wav").write_bytes(b"x"); (d2 / "result.json").write_text("{}")
    assert list(cw.merge_errors(ed, dirs)) == ["3"]
    assert json.loads((ed / "errors.json").read_text()).keys() == {"3"} and not list(ed.glob("errors.*.json"))


def test_multiprocess_root_layout(tmp_path):
    ids = list(range(1, 7))
    mk_root_batch(tmp_path / "b", ids)
    root = tmp_path / "drive"
    env = dict(os.environ, SS_FAKE_RENDER="1")
    p = subprocess.run([sys.executable, "-u", "-m", "backend.worker.colab_worker", "--batch", str(tmp_path / "b"),
                        "--results-root", str(root), "--models-dir", str(tmp_path / "m"), "--workers", "2"],
                       cwd=ROOT, env=env, capture_output=True, text=True, timeout=120)
    assert p.returncode == 0, p.stdout + p.stderr
    for i in ids:
        d = root / "batch_results/epic/kanda/sarga_001" / f"v-{i:03d}"
        assert (d / "chant.wav").exists() and (d / "result.json").exists()
    assert "[w0]" in p.stdout and "[w1]" in p.stdout
    assert not list((root / "batch_results/_batches/b").glob("errors.*.json"))


def test_notebook_zip_layout(tmp_path):
    """Run the notebook's zip-building cell fragment against a fake Drive tree."""
    import zipfile
    nb = json.loads((ROOT / "notebooks" / "colab_batch.ipynb").read_text(encoding="utf-8"))
    src = "".join([c for c in nb["cells"] if c["cell_type"] == "code"][0]["source"])
    a, b = src.index("# ---- 9."), src.index("# ---- 10.")
    frag = src[a:b]
    R = tmp_path / "drive"; OUT = R / "batch_results/_batches/b"; OUT.mkdir(parents=True)
    job_dirs = {"1": "batch_results/e/k/sarga_001/v-1", "2": "batch_results/e/k/sarga_001/v-2"}
    for j, d in job_dirs.items():
        (R / d).mkdir(parents=True); (R / d / "chant.wav").write_bytes(b"w" + j.encode()); (R / d / "result.json").write_text("{}")
    (OUT / "errors.json").write_text(json.dumps({"9": "bad"}))
    g = dict(Path=Path, json=json, zipfile=zipfile, R=str(R), OUT=str(OUT), job_dirs=job_dirs, done_before=0, rc=0,
             is_done=lambda j: (R / job_dirs[j] / "result.json").exists())
    exec(frag, g)
    with zipfile.ZipFile(OUT / "results.zip") as z:
        assert sorted(z.namelist()) == ["results/1/chant.wav", "results/1/result.json", "results/2/chant.wav",
                                        "results/2/result.json", "results/errors.json"]
        assert json.loads(z.read("results/errors.json")) == {"9": "bad"}
