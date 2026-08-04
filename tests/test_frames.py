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
