"""End-to-end `run` under PIPELINE_FAKE=1 (fake render + fake align, LocalStore). All verse text is FIXTURE text."""
import json
from pathlib import Path

import pytest

from pipeline import runner
from pipeline.__main__ import build_parser
from pipeline.catalog import load_state
from pipeline.stores import open_store


@pytest.fixture(autouse=True)
def fake_mode(monkeypatch):
    monkeypatch.setenv("PIPELINE_FAKE", "1")
    monkeypatch.delenv("PIPELINE_FAKE_ALIGN_FAIL", raising=False)
    monkeypatch.setenv("PIPELINE_ENV", "local")


def make_tree(root: Path, verses: dict) -> Path:
    """verses: {n: lines|None}. FIXTURE epic-json tree (baala sarga 1); None = verse without any usable text."""
    d = root / "baala" / "sarga_001"
    d.mkdir(parents=True)
    for n, lines in verses.items():
        text = {} if lines is None else {"critical_smith": {"lines": lines}}
        (d / f"verse_{n:03d}.json").write_text(json.dumps(
            {"id": f"baala-001-{n:03d}", "kanda": "baala", "sarga": 1, "seq_in_sarga": n, "text": text}), encoding="utf-8")
    return root


def fixture_lines(n):
    return [f"FIXTURE pada one {n}", f"FIXTURE pada two {n}"]


def run_args(tmp_path, tree, *extra):
    return build_parser().parse_args(
        ["run", "--input-epic-json", str(tree), "--dest", str(tmp_path / "store"), "--env", "local", "--workers", "1",
         "--scratch", str(tmp_path / "scratch"), *extra])


def files(root: Path):
    return sorted(str(p.relative_to(root)) for p in root.rglob("*") if p.is_file()) if root.exists() else []


def test_end_to_end_and_skip_done(tmp_path):
    tree = make_tree(tmp_path / "tree", {i: fixture_lines(i) for i in range(1, 5)})
    # "interrupted" first run: only 2 verses
    assert runner.run(run_args(tmp_path, tree, "--limit", "2")) == 0
    assert runner.LAST_RUN["counts"] == {"ok": 2}
    store = open_store(str(tmp_path / "store"))
    assert len(load_state(store)) == 2
    # restart with the same arguments minus the limit: only the missing two are rendered
    assert runner.run(run_args(tmp_path, tree)) == 0
    assert runner.LAST_RUN["planned"] == 2 and runner.LAST_RUN["rendered"] == 2
    state = load_state(store)
    assert sorted(state) == [f"baala-001-{i:03d}" for i in range(1, 5)]
    assert all(v["status"] == "ok" and v["audio"] and v["align"] and not v.get("wav") for v in state.values())
    # nothing left to do
    assert runner.run(run_args(tmp_path, tree)) == 0
    assert runner.LAST_RUN["planned"] == 0
    # blobs are readable by offset: MP3 and alignment JSON
    e = state["baala-001-001"]
    al = json.loads(store.read_range(f"segments/{e['segment']}.align.pack", e["align"]["off"], e["align"]["len"]))
    assert al["lines"] and al["audio_duration"] > 0
    # run logs were published
    rid = runner.LAST_RUN["run_id"]
    assert store.exists(f"runs/{rid}/metrics.json")


def test_dry_run_writes_nothing(tmp_path, capsys):
    tree = make_tree(tmp_path / "tree", {1: fixture_lines(1), 2: fixture_lines(2)})
    args = run_args(tmp_path, tree, "--dry-run")
    assert runner.run(args) == 0
    assert runner.LAST_RUN["dry_run"] and runner.LAST_RUN["planned"] == 2
    assert not (tmp_path / "store").exists()
    assert json.loads(capsys.readouterr().out)["summary"]["selected"] == 2
    # also against an existing store
    assert runner.run(run_args(tmp_path, tree)) == 0
    before = files(tmp_path / "store")
    assert runner.run(run_args(tmp_path, tree, "--dry-run", "--force")) == 0
    assert files(tmp_path / "store") == before


def test_no_text_row(tmp_path):
    tree = make_tree(tmp_path / "tree", {1: fixture_lines(1), 2: None})
    assert runner.run(run_args(tmp_path, tree)) == 0
    store = open_store(str(tmp_path / "store"))
    state = load_state(store)
    assert state["baala-001-001"]["status"] == "ok"
    assert state["baala-001-002"]["status"] == "failed" and state["baala-001-002"]["error"] == "no_text"
    failed = store.read(f"runs/{runner.LAST_RUN['run_id']}/failed.jsonl").decode()
    assert "baala-001-002" in failed and "no_text" in failed
    # a rerun does not add the row again
    assert runner.run(run_args(tmp_path, tree)) == 0
    assert runner.LAST_RUN["invalid_rows"] == 0


def test_align_failure_then_realign_only(tmp_path, monkeypatch):
    lines = {1: fixture_lines(1), 2: ["FIXTURE ALIGNFAIL pada", "FIXTURE pada two"]}
    tree = make_tree(tmp_path / "tree", lines)
    monkeypatch.setenv("PIPELINE_FAKE_ALIGN_FAIL", "1")
    assert runner.run(run_args(tmp_path, tree)) == 0
    assert runner.LAST_RUN["counts"] == {"ok": 1, "align_failed": 1}
    store = open_store(str(tmp_path / "store"))
    s = load_state(store)["baala-001-002"]
    assert s["status"] == "align_failed" and s["audio"] and s["wav"] and not s["align"]
    assert "alignment" in s["error"]
    assert store.read_range(f"segments/{s['segment']}.wav.pack", s["wav"]["off"], 4) == b"RIFF"

    # aligner healthy again: --only align_failed re-aligns from the stored WAV without rendering
    monkeypatch.delenv("PIPELINE_FAKE_ALIGN_FAIL")
    assert runner.run(run_args(tmp_path, tree, "--only", "align_failed")) == 0
    assert runner.LAST_RUN["planned"] == 1 and runner.LAST_RUN["rendered"] == 0
    s2 = load_state(store)["baala-001-002"]
    assert s2["status"] == "ok" and s2["align"] and not s2.get("wav")
    assert s2["audio"] and s2["audio"]["len"] == s["audio"]["len"]      # MP3 reused (copied into the new segment)


def test_render_failure_is_a_failed_row_and_run_continues(tmp_path):
    tree = make_tree(tmp_path / "tree", {1: ["FIXTURE RENDERFAIL pada"], 2: fixture_lines(2)})
    assert runner.run(run_args(tmp_path, tree)) == 0
    state = load_state(open_store(str(tmp_path / "store")))
    assert state["baala-001-001"]["status"] == "failed" and "render_error" in state["baala-001-001"]["error"]
    assert state["baala-001-002"]["status"] == "ok"


def test_cli_only_passes_given_flags():
    a = build_parser().parse_args(["run", "--input", "x.jsonl", "--steps", "12"])
    assert runner.build_cli(a) == {"steps": 12}
    a = build_parser().parse_args(["run", "--input", "x.jsonl"])
    assert runner.build_cli(a) == {}
    sel = runner.build_selection(build_parser().parse_args(
        ["run", "--input", "x", "--book", "baala,ayodhya", "--chapters", "1-3", "--shard", "1/4", "--ids", "a,b"]))
    assert sel.book == ["baala", "ayodhya"] and sel.chapters == {1, 2, 3} and sel.shard == (1, 4) and sel.ids == {"a", "b"}


def test_scratch_root_kaggle():
    class A:
        scratch = None
    assert runner._scratch_root(A(), "kaggle") == (Path("/kaggle/temp/pipeline_scratch"), False)


def test_max_hours_stops_early_exit_zero(tmp_path):
    tree = make_tree(tmp_path / "tree", {i: fixture_lines(i) for i in range(1, 9)})
    assert runner.run(run_args(tmp_path, tree, "--max-hours", "0.00001")) == 0
    assert runner.LAST_RUN["exit"] == 0
    store = open_store(str(tmp_path / "store"))
    rid = runner.LAST_RUN["run_id"]
    assert store.exists(f"runs/{rid}/metrics.json")
    assert runner.LAST_RUN["stopped_early"] or runner.LAST_RUN["completed"] >= runner.LAST_RUN["planned"]


def test_no_max_hours_unchanged(tmp_path):
    tree = make_tree(tmp_path / "tree", {i: fixture_lines(i) for i in range(1, 3)})
    assert runner.run(run_args(tmp_path, tree)) == 0
    assert runner.LAST_RUN["stopped_early"] is False and runner.LAST_RUN["counts"] == {"ok": 2}
