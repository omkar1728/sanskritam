"""Pure-function tests for pipeline.hardware (no GPU, no network)."""
import json

from pipeline import hardware as H


def test_detect_env_override():
    assert H.detect_env({"PIPELINE_ENV": "colab"}, probe=lambda t: "x") == "colab"
    assert H.detect_env({"PIPELINE_ENV": "local"}, probe=lambda t: "x") == "local"


def test_detect_env_colab_and_aws_and_local():
    assert H.detect_env({"COLAB_GPU": "1"}, probe=lambda t: None) == "colab"
    assert H.detect_env({"AWS_EXECUTION_ENV": "AWS_EC2"}, probe=lambda t: None) == "aws"
    assert H.detect_env({}, probe=lambda t: "token") == "aws"
    # no colab module in the test env, no IMDS answer
    assert H.detect_env({}, probe=lambda t: None) in ("local", "colab")


def test_detect_device_env_and_request(monkeypatch):
    monkeypatch.setenv("PIPELINE_DEVICE", "cpu")
    assert H.detect_device(None) == "cpu"
    assert H.detect_device("cuda") == "cuda"          # explicit request wins
    monkeypatch.delenv("PIPELINE_DEVICE")
    monkeypatch.setenv("PIPELINE_FAKE", "1")
    assert H.detect_device("auto") == "cpu"


def test_gpu_sizing_t4_formula():
    s = H.size_workers("cuda", 15000, 14.0, 4)
    # min(15000//2600=5, 14//3.5=4, 4-1=3) = 3 render workers; post = max(1, 4-3) = 1
    assert s["render"] == 3 and s["post"] == 1 and s["gpu_groups"] == 1
    assert s["render"] * 3.5 + s["post"] * 1.5 <= 14.0


def test_gpu_sizing_calibration_caps_workers():
    s = H.size_workers("cuda", 15000, 14.0, 4, calib={"best_workers": 1})
    assert s["render"] == 1 and s["post"] == 3


def test_requested_overrides_calibration():
    s = H.size_workers("cuda", 15000, 14.0, 4, calib={"best_workers": 1}, requested=2)
    assert s["render"] == 2


def test_vram_limits_workers():
    s = H.size_workers("cuda", 3000, 30.0, 16)
    assert s["render"] == 1


def test_multi_gpu_one_group_each():
    s = H.size_workers("cuda", 15000, 60.0, 16, calib={"best_workers": 1}, n_gpus=2)
    assert s["gpu_groups"] == 2 and s["render"] == 2 and s["post"] == 14


def test_cpu_only_ram_bound():
    s = H.size_workers("cpu", 0, 6.0, 4)
    assert s["render"] == 1
    assert s["render"] * 3.5 + s["post"] * 1.5 <= 6.0
    assert s["post"] >= 1


def test_cpu_many_cores_enough_ram():
    s = H.size_workers("cpu", 0, 40.0, 8)
    assert s["render"] == 8 and s["post"] == 1 or s["render"] * 3.5 + s["post"] * 1.5 <= 40.0


def test_never_exceeds_ram_when_possible():
    for ram in (6.0, 8.0, 15.0, 31.0):
        for cores in (2, 4, 8):
            s = H.size_workers("cuda", 24000, ram, cores)
            if ram >= 5.0:
                assert s["render"] * 3.5 + s["post"] * 1.5 <= ram, (ram, cores, s)


def test_tiny_ram_warns_but_returns_one_each():
    s = H.size_workers("cpu", 0, 2.0, 4)
    assert s["render"] == 1 and s["post"] == 1
    assert any("warning" in n for n in s["notes"])


def test_calib_path_and_load(tmp_path, monkeypatch):
    monkeypatch.setattr(H.Path, "home", classmethod(lambda cls: tmp_path))
    p = H.calib_path("Tesla T4")
    assert p.name == "calib-Tesla_T4.json"
    assert H.load_calib("Tesla T4") is None
    p.parent.mkdir(parents=True)
    p.write_text(json.dumps({"best_workers": 2}))
    assert H.load_calib("Tesla T4")["best_workers"] == 2
    assert H.load_calib(None) is None


def test_detect_env_kaggle(tmp_path):
    none = tmp_path / "absent"
    assert H.detect_env({"PIPELINE_ENV": "kaggle"}, probe=lambda t: None, kaggle_dir=none) == "kaggle"
    assert H.detect_env({"KAGGLE_KERNEL_RUN_TYPE": "Interactive"}, probe=lambda t: None, kaggle_dir=none) == "kaggle"
    assert H.detect_env({"KAGGLE_URL_BASE": "https://www.kaggle.com"}, probe=lambda t: None, kaggle_dir=none) == "kaggle"
    assert H.detect_env({}, probe=lambda t: None, kaggle_dir=tmp_path) == "kaggle"
    assert H.detect_env({"COLAB_GPU": "1"}, probe=lambda t: None, kaggle_dir=tmp_path) == "colab"
    assert H.detect_env({"PIPELINE_ENV": "local"}, probe=lambda t: None, kaggle_dir=tmp_path) == "local"
    assert H.detect_env({"AWS_EXECUTION_ENV": "x"}, probe=lambda t: None, kaggle_dir=tmp_path) == "kaggle"
