import importlib.util
import json
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parent.parent / "skills" / "audio-tldr" / "scripts" / "frames.py"
spec = importlib.util.spec_from_file_location("frames", SCRIPT)
frames = importlib.util.module_from_spec(spec)
spec.loader.exec_module(frames)


def test_parse_at_list_mixed_formats():
    assert frames.parse_at_list("90, 3:35, 600") == [90.0, 215.0, 600.0]


def test_parse_at_list_hms_and_dedup_sorted():
    assert frames.parse_at_list("1:00:05,65,65") == [65.0, 3605.0]


def test_parse_at_list_rejects_bad_input():
    for bad in ("", " , ", "-5", "1:2:3:4", "abc"):
        with pytest.raises(ValueError):
            frames.parse_at_list(bad)


def test_frame_filename_zero_pads():
    assert frames.frame_filename(1, 32.4) == "001-0000m32s.jpg"
    assert frames.frame_filename(42, 3605.9) == "042-0060m05s.jpg"


SHOWINFO = """[Parsed_showinfo_1 @ 0x600] n:   0 pts:  12800 pts_time:32.4    fmt:yuv420p
[Parsed_showinfo_1 @ 0x600] n:   1 pts:  26000 pts_time:65.0    fmt:yuv420p
frame=    2 fps=0.0"""


def test_parse_showinfo_times():
    assert frames.parse_showinfo_times(SHOWINFO) == [32.4, 65.0]


def test_parse_showinfo_times_empty():
    assert frames.parse_showinfo_times("no frames here") == []


def test_apply_min_gap_drops_bursts():
    assert frames.apply_min_gap([10.0, 10.8, 11.5, 20.0], 2.0) == [10.0, 20.0]


def test_downsample_evenly_keeps_ends():
    times = [float(i) for i in range(10)]
    out = frames.downsample_evenly(times, 4)
    assert len(out) == 4 and out[0] == 0.0 and out[-1] == 9.0


def test_downsample_evenly_noop_under_limit():
    assert frames.downsample_evenly([1.0, 2.0], 5) == [1.0, 2.0]


def test_validate_threshold_range():
    assert frames.validate_threshold(0.10) == 0.10
    for bad in (0.0, 0.01, 0.95, -1):
        with pytest.raises(ValueError):
            frames.validate_threshold(bad)


def test_build_detect_cmd():
    cmd = frames.build_detect_cmd("/tmp/v.mp4", 0.1)
    assert cmd[0] == "ffmpeg" and "/tmp/v.mp4" in cmd
    assert any("gt(scene,0.1)" in c and "showinfo" in c for c in cmd)
    assert cmd[-3:] == ["-f", "null", "-"]


def test_build_extract_cmd_seeks_before_input():
    cmd = frames.build_extract_cmd("/tmp/v.mp4", 65.0, "/tmp/out.jpg", 2)
    assert cmd.index("-ss") < cmd.index("-i")
    assert "-frames:v" in cmd and "/tmp/out.jpg" == cmd[-1]


def test_build_ytdlp_cmd_caps_720p():
    cmd = frames.build_ytdlp_cmd("https://youtu.be/x", Path("/tmp/e"))
    assert cmd[0] == "yt-dlp" and "--no-playlist" in cmd
    assert any("height<=720" in c for c in cmd)
    assert any(str(Path("/tmp/e") / "video.%(ext)s") in c for c in cmd)


def test_build_ffprobe_cmd():
    cmd = frames.build_ffprobe_cmd("/tmp/v.mp4")
    assert cmd[0] == "ffprobe" and "/tmp/v.mp4" in cmd


def _mani(mode="scene", threshold=0.1, min_gap=2.0, ts_list=(32.4, 65.0)):
    return {"mode": mode, "threshold": threshold, "min_gap": min_gap,
            "frames": [{"i": i + 1, "ts": t, "file": frames.frame_filename(i + 1, t)}
                       for i, t in enumerate(ts_list)]}


def test_scene_cache_ok_same_params():
    assert frames.scene_cache_ok(_mani(), 0.1, 2.0)


def test_scene_cache_miss_on_param_change():
    assert not frames.scene_cache_ok(_mani(), 0.2, 2.0)
    assert not frames.scene_cache_ok(_mani(mode="at"), 0.1, 2.0)


def test_missing_at_times_tolerance():
    m = _mani(mode="at")
    assert frames.missing_at_times(m, [32.0, 65.4, 100.0]) == [100.0]


def test_build_manifest_shape():
    m = frames.build_manifest("scene", 0.1, 2.0, "https://x",
                              [{"i": 1, "ts": 5.0, "file": "001-0000m05s.jpg"}],
                              duration=600.5)
    assert m["mode"] == "scene" and m["frames"][0]["file"] == "001-0000m05s.jpg"
    assert "created" in m and m["source"] == "https://x" and m["duration"] == 600.5


def test_write_min_meta_creates_and_never_overwrites(tmp_path):
    frames.write_min_meta(tmp_path, "https://x", "My Talk")
    meta = json.loads((tmp_path / "meta.json").read_text())
    assert meta["frames_only"] is True and meta["title"] == "My Talk"
    (tmp_path / "meta.json").write_text('{"title": "full"}')
    frames.write_min_meta(tmp_path, "https://x", "My Talk")
    assert json.loads((tmp_path / "meta.json").read_text())["title"] == "full"


def test_cache_key_shared_with_transcribe():
    t_spec = importlib.util.spec_from_file_location(
        "transcribe", SCRIPT.parent / "transcribe.py")
    transcribe = importlib.util.module_from_spec(t_spec)
    t_spec.loader.exec_module(transcribe)
    url = "https://youtu.be/abc?si=track"
    assert frames.cache_key(url) == transcribe.cache_key(url)


class StubRunner:
    """Simulates subprocess.run for ffmpeg/ffprobe/yt-dlp."""
    def __init__(self, scene_times=(32.4, 65.0), tmp=None):
        self.calls, self.scene_times, self.tmp = [], scene_times, tmp

    def __call__(self, cmd, **kw):
        self.calls.append(cmd)
        out, err, rc = "", "", 0
        if cmd[0] == "yt-dlp":
            (Path(self.tmp) / "video.mp4").write_bytes(b"fake")
        elif cmd[0] == "ffmpeg" and "null" in cmd:
            err = "\n".join(f"pts_time:{t}" for t in self.scene_times)
        elif cmd[0] == "ffmpeg":
            Path(cmd[-1]).write_bytes(b"jpg")
        elif cmd[0] == "ffprobe":
            out = "600.5\n"
        return subprocess.CompletedProcess(cmd, rc, stdout=out, stderr=err)


def _run_main(argv, monkeypatch, tmp_path, capsys, scene_times=(32.4, 65.0)):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    src = tmp_path / "talk.mp4"
    if not src.exists():
        src.write_bytes(b"local-video-bytes")
    entry = frames.cache_dir() / frames.cache_key(str(src))
    entry.mkdir(parents=True, exist_ok=True)
    runner = StubRunner(scene_times=scene_times, tmp=entry)
    rc = frames.main([str(src)] + argv, run=runner)
    out = json.loads(capsys.readouterr().out.strip())
    return rc, out, runner


def test_main_scene_mode_extracts_and_caches(monkeypatch, tmp_path, capsys):
    rc, out, runner = _run_main([], monkeypatch, tmp_path, capsys)
    assert rc == 0 and out["frame_count"] == 2 and out["cache_hit"] is False
    assert out["mode"] == "scene" and out["duration"] == 600.5
    rc2, out2, runner2 = _run_main([], monkeypatch, tmp_path, capsys)
    assert out2["cache_hit"] is True and runner2.calls == []
    assert out2["duration"] == 600.5


def test_main_at_mode(monkeypatch, tmp_path, capsys):
    rc, out, _ = _run_main(["--at", "10,20"], monkeypatch, tmp_path, capsys)
    assert rc == 0 and out["mode"] == "at" and out["frame_count"] == 2


def test_main_local_file_never_deleted(monkeypatch, tmp_path, capsys):
    _run_main([], monkeypatch, tmp_path, capsys)
    assert (tmp_path / "talk.mp4").exists()


def test_at_after_scene_returns_only_requested_frames(monkeypatch, tmp_path, capsys):
    _run_main([], monkeypatch, tmp_path, capsys)                    # scene: 32.4, 65.0
    rc, out, _ = _run_main(["--at", "10"], monkeypatch, tmp_path, capsys)
    assert rc == 0 and out["mode"] == "at"
    assert [f["ts"] for f in out["frames"]] == [10.0]               # 不混入 scene 幀


def test_at_near_scene_frame_not_served_from_scene_cache(monkeypatch, tmp_path, capsys):
    _run_main([], monkeypatch, tmp_path, capsys)                    # scene: 32.4, 65.0
    rc, out, _ = _run_main(["--at", "32"], monkeypatch, tmp_path, capsys)
    assert out["mode"] == "at" and out["cache_hit"] is False        # 32≈32.4 也不能拿 scene 快取充數
    assert [f["ts"] for f in out["frames"]] == [32.0]


def test_scene_after_at_leaves_no_orphan_jpgs(monkeypatch, tmp_path, capsys):
    _run_main(["--at", "10,20"], monkeypatch, tmp_path, capsys)
    rc, out, _ = _run_main([], monkeypatch, tmp_path, capsys)       # scene: 32.4, 65.0
    fdir = Path(out["frames_dir"])
    on_disk = sorted(p.name for p in fdir.glob("*.jpg"))
    assert on_disk == sorted(f["file"] for f in out["frames"])      # 舊 at 幀不殘留


def test_at_incremental_append_still_works(monkeypatch, tmp_path, capsys):
    _run_main(["--at", "10,20"], monkeypatch, tmp_path, capsys)
    rc, out, runner = _run_main(["--at", "10,20,30"], monkeypatch, tmp_path, capsys)
    assert out["frame_count"] == 3
    extracts = [c for c in runner.calls if c[0] == "ffmpeg" and "null" not in c]
    assert len(extracts) == 1                                       # 只補抓缺的 30s


def test_force_rebuild_leaves_no_stale_jpgs(monkeypatch, tmp_path, capsys):
    _run_main([], monkeypatch, tmp_path, capsys, scene_times=(32.4, 65.0))
    rc, out, _ = _run_main(["--force"], monkeypatch, tmp_path, capsys,
                           scene_times=(40.0,))
    fdir = Path(out["frames_dir"])
    on_disk = sorted(p.name for p in fdir.glob("*.jpg"))
    assert on_disk == ["001-0000m40s.jpg"]                          # 舊 32s/65s 幀已清


def test_main_bad_threshold_exits_2(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    src = tmp_path / "talk.mp4"
    src.write_bytes(b"x")
    assert frames.main([str(src), "--threshold", "5"], run=StubRunner()) == 2
