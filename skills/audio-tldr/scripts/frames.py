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


def _find_video(entry: Path):
    vids = sorted(entry.glob("video.*"))
    return vids[0] if vids else None


def _title_for(source: str, run) -> str:
    if not is_url(source):
        return Path(source).stem
    try:
        r = run(["yt-dlp", "--no-download", "--print", "title", source],
                capture_output=True, text=True, timeout=30)
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip().splitlines()[0]
    except Exception:
        pass
    return source


def _probe_duration(video, run):
    if video is None:
        return None
    try:
        r = run(build_ffprobe_cmd(video), capture_output=True, text=True)
        return float(r.stdout.strip()) if r.returncode == 0 and r.stdout.strip() else None
    except Exception:
        return None


def _emit(fdir: Path, manifest: dict, cache_hit: bool, video_kept: bool) -> int:
    print(json.dumps({
        "frames_dir": str(fdir), "frame_count": len(manifest["frames"]),
        "mode": manifest["mode"], "frames": manifest["frames"],
        "cache_hit": cache_hit, "video_kept": video_kept,
        "duration": manifest.get("duration"),
    }, ensure_ascii=False))
    return 0


def main(argv=None, run=subprocess.run) -> int:
    ap = argparse.ArgumentParser(
        description="Extract video frames (scene-detect or timestamps), cached.")
    ap.add_argument("source")
    ap.add_argument("--at")
    ap.add_argument("--threshold", default="0.10")
    ap.add_argument("--min-gap", type=float, default=2.0)
    ap.add_argument("--max-frames", type=int, default=120)
    ap.add_argument("--keep-video", action="store_true")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--quality", type=int, default=2)
    a = ap.parse_args(argv)

    try:
        at_times = parse_at_list(a.at) if a.at else None
        threshold = validate_threshold(a.threshold)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    source = a.source
    key = cache_key(source)
    entry = cache_dir() / key
    fdir = entry / "frames"
    mani_path = fdir / "manifest.json"
    mode = "at" if at_times else "scene"

    manifest = None
    if mani_path.exists() and not a.force:
        manifest = json.loads(mani_path.read_text())
        hit = (scene_cache_ok(manifest, threshold, a.min_gap) if mode == "scene"
               else not missing_at_times(manifest, at_times))
        if hit:
            return _emit(fdir, manifest, cache_hit=True,
                         video_kept=_find_video(entry) is not None)

    # ---- acquire video ----
    if is_url(source):
        video = _find_video(entry)
        if video is None:
            entry.mkdir(parents=True, exist_ok=True)
            r = run(build_ytdlp_cmd(source, entry), capture_output=True, text=True)
            if r.returncode != 0:
                print("error: video download failed — is yt-dlp installed and the "
                      "URL reachable?\n" + (r.stderr or "")[-2000:], file=sys.stderr)
                return 2
            video = _find_video(entry)
            if video is None:
                print("error: yt-dlp reported success but no video file found",
                      file=sys.stderr)
                return 2
    else:
        video = Path(source)
        if not video.exists():
            print(f"error: file not found: {source}", file=sys.stderr)
            return 2
        if a.keep_video:
            print("note: --keep-video is a no-op for local files (source is never "
                  "touched)", file=sys.stderr)

    # ---- decide timestamps ----
    if mode == "scene":
        r = run(build_detect_cmd(video, threshold), capture_output=True, text=True)
        if r.returncode != 0:
            print("error: ffmpeg scene detection failed — is ffmpeg installed?\n"
                  + (r.stderr or "")[-2000:], file=sys.stderr)
            return 2
        times = apply_min_gap(parse_showinfo_times(r.stderr), a.min_gap)
        if len(times) > a.max_frames:
            print(f"note: {len(times)} scene changes found, downsampling evenly to "
                  f"{a.max_frames} (raise --max-frames to keep more)", file=sys.stderr)
            times = downsample_evenly(times, a.max_frames)
        if not times:
            print("note: no scene changes detected — try lowering --threshold "
                  "(e.g. 0.05)", file=sys.stderr)
        existing = []
    else:
        existing = manifest["frames"] if manifest else []
        times = missing_at_times(manifest, at_times) if manifest else at_times

    # ---- extract ----
    fdir.mkdir(parents=True, exist_ok=True)
    entries = list(existing)
    for ts in times:
        i = len(entries) + 1
        out_path = fdir / frame_filename(i, ts)
        r = run(build_extract_cmd(video, ts, out_path, a.quality),
                capture_output=True, text=True)
        if r.returncode != 0:
            print("error: ffmpeg frame extraction failed\n"
                  + (r.stderr or "")[-2000:], file=sys.stderr)
            return 2
        entries.append({"i": i, "ts": ts, "file": out_path.name})
    entries.sort(key=lambda e: e["ts"])

    duration = _probe_duration(video, run)
    manifest = build_manifest(mode, threshold, a.min_gap, source, entries,
                              duration=duration)
    mani_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=1))
    write_min_meta(entry, source, _title_for(source, run))

    video_kept = False
    if is_url(source):
        if a.keep_video:
            video_kept = True
        else:
            video.unlink(missing_ok=True)

    return _emit(fdir, manifest, cache_hit=False, video_kept=video_kept)


if __name__ == "__main__":
    sys.exit(main())
