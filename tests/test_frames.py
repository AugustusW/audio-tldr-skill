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
