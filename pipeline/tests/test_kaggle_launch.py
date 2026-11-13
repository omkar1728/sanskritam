"""Kaggle launcher tests: fakes only, no kaggle command, no network, no models."""
import json
import re
from pathlib import Path

import pytest

from pipeline.kaggle_run import launch

FIXTURE = {"schema": 1, "verse_id": "fixture-001-001", "padas": ["FIXTURE a", "FIXTURE b"]}


def _jsonl(tmp_path, recs, name="v.jsonl"):
    p = tmp_path / name
    p.write_text("\n".join(json.dumps(r) for r in recs) + "\n", encoding="utf-8")
    return p


@pytest.fixture
def no_kaggle(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("kaggle CLI must not run")
    monkeypatch.setattr(launch, "kaggle", boom)


def _dry(tmp_path, monkeypatch, extra=()):
    monkeypatch.setattr(launch.tempfile, "mkdtemp", lambda prefix="": str(tmp_path / "stage_x"))
    (tmp_path / "stage_x").mkdir()
    j = _jsonl(tmp_path, [FIXTURE])
    rc = launch.main(["push", "--user", "u", "--jsonl", str(j), "--dry-run",
                      "--run-args", "--chapters 1-2", *extra])
    return rc, tmp_path / "stage_x"


def test_dry_run_staging(tmp_path, monkeypatch, no_kaggle, capsys):
    rc, stage = _dry(tmp_path, monkeypatch)
    assert rc == 0
    files = [p for p in stage.rglob("*") if p.is_file()]
    rel = {str(p.relative_to(stage)) for p in files}
    assert "code/pipeline/__main__.py" in rel
    assert "code/backend/engine/synth.py" in rel and "code/backend/app/config.py" in rel
    assert "verses/v.jsonl" in rel and "kernel/kernel.py" in rel
    cfg = json.loads((stage / "code/config.json").read_text())
    assert cfg["run_args"] == ["--chapters", "1-2"] and cfg["max_hours"] == 11 and cfg["dest"].startswith("s3://")
    meta = json.loads((stage / "kernel/kernel-metadata.json").read_text())
    assert meta["enable_gpu"] is True and meta["enable_internet"] is True and meta["kernel_type"] == "script"
    assert meta["is_private"] is True and len(meta["dataset_sources"]) == 2
    for d in ("code", "verses"):
        assert json.loads((stage / d / "dataset-metadata.json").read_text())["id"].startswith("u/")
    bad = re.compile(r"\.(pt|pth|wav|mp3|env|pem|key|pyc)$|EdgeSanskrit|secret|__pycache__|/tests/", re.I)
    assert not [r for r in rel if bad.search("/" + r)]
    assert not [r for r in rel if r.startswith("code/") and r.endswith(".jsonl")]
    assert "no kaggle command was run" in capsys.readouterr().out


def test_push_aborts_on_invalid(tmp_path, no_kaggle, capsys):
    j = _jsonl(tmp_path, [FIXTURE, {"schema": 1, "verse_id": "Bad ID", "padas": []}])
    rc = launch.main(["push", "--user", "u", "--jsonl", str(j)])
    assert rc == 1
    assert "ABORT" in capsys.readouterr().out


def test_kernel_compiles_and_is_stdlib():
    src = (Path(launch.__file__).with_name("kernel.py")).read_text()
    tree = compile(src, "kernel.py", "exec", dont_inherit=True)
    import ast
    mods = set()
    for n in ast.walk(ast.parse(src)):
        if isinstance(n, ast.Import):
            mods |= {a.name.split(".")[0] for a in n.names}
        elif isinstance(n, ast.ImportFrom) and n.level == 0:
            mods.add(n.module.split(".")[0])
    import sys
    assert tree and mods <= set(sys.stdlib_module_names) | {"kaggle_secrets"}
