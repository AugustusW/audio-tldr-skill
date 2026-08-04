#!/usr/bin/env python3
"""audio-tldr frame extraction: scene-detect / timestamp -> jpg frames, cached."""
import argparse
import importlib.util
import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_t_spec = importlib.util.spec_from_file_location("_transcribe", _HERE / "transcribe.py")
_transcribe = importlib.util.module_from_spec(_t_spec)
_t_spec.loader.exec_module(_transcribe)
cache_key = _transcribe.cache_key
cache_dir = _transcribe.cache_dir
is_url = _transcribe.is_url


def parse_at_list(s: str) -> list:
    out = []
    for tok in s.split(","):
        tok = tok.strip()
        if not tok:
            continue
        if ":" in tok:
            parts = tok.split(":")
            if len(parts) not in (2, 3):
                raise ValueError(f"bad timestamp: {tok!r}")
            sec = 0.0
            for p in parts:
                sec = sec * 60 + float(p)
        else:
            sec = float(tok)
        if sec < 0:
            raise ValueError(f"negative timestamp: {tok!r}")
        out.append(sec)
    if not out:
        raise ValueError("empty --at list")
    return sorted(set(out))


def frame_filename(i: int, ts: float) -> str:
    m, s = int(ts) // 60, int(ts) % 60
    return f"{i:03d}-{m:04d}m{s:02d}s.jpg"


_PTS_RE = re.compile(r"pts_time:(\d+(?:\.\d+)?)")


def parse_showinfo_times(stderr: str) -> list:
    return [float(m) for m in _PTS_RE.findall(stderr)]


def apply_min_gap(times: list, min_gap: float) -> list:
    out = []
    for t in times:
        if not out or t - out[-1] >= min_gap:
            out.append(t)
    return out


def downsample_evenly(times: list, max_n: int) -> list:
    if len(times) <= max_n:
        return list(times)
    if max_n == 1:
        return [times[0]]
    step = (len(times) - 1) / (max_n - 1)
    idx = sorted({round(i * step) for i in range(max_n)})
    return [times[i] for i in idx]


def validate_threshold(f) -> float:
    f = float(f)
    if not 0.02 <= f <= 0.9:
        raise ValueError(f"--threshold must be between 0.02 and 0.9, got {f}")
    return f


def build_detect_cmd(video, threshold: float) -> list:
    return ["ffmpeg", "-hide_banner", "-i", str(video),
            "-vf", f"select='gt(scene,{threshold})',showinfo",
            "-f", "null", "-"]


def build_extract_cmd(video, ts: float, out_path, quality: int) -> list:
    return ["ffmpeg", "-hide_banner", "-y", "-ss", f"{ts:.3f}", "-i", str(video),
            "-frames:v", "1", "-q:v", str(quality), str(out_path)]


def build_ytdlp_cmd(url: str, entry: Path) -> list:
    return ["yt-dlp", "-f", "bv*[height<=720]+ba/b[height<=720]/b",
            "--no-playlist", "-o", str(entry / "video.%(ext)s"), url]


def build_ffprobe_cmd(video) -> list:
    return ["ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "csv=p=0", str(video)]


def scene_cache_ok(manifest: dict, threshold: float, min_gap: float) -> bool:
    return (manifest.get("mode") == "scene"
            and manifest.get("threshold") == threshold
            and manifest.get("min_gap") == min_gap)


def missing_at_times(manifest: dict, requested: list, tol: float = 0.5) -> list:
    have = [f["ts"] for f in manifest.get("frames", [])]
    return [t for t in requested if not any(abs(t - h) <= tol for h in have)]


def build_manifest(mode, threshold, min_gap, source, frame_entries, duration=None) -> dict:
    return {"mode": mode, "threshold": threshold, "min_gap": min_gap,
            "source": source, "created": datetime.now().isoformat(timespec="seconds"),
            "duration": duration, "frames": frame_entries}


def write_min_meta(entry: Path, source: str, title: str) -> None:
    meta_path = entry / "meta.json"
    if meta_path.exists():
        return
    entry.mkdir(parents=True, exist_ok=True)
    meta_path.write_text(json.dumps({
        "source": source, "title": title, "frames_only": True,
        "created": datetime.now().isoformat(timespec="seconds"),
    }, ensure_ascii=False))
