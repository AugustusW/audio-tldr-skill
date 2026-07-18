#!/usr/bin/env python3
"""audio-tldr transcription engine: download -> detect backend -> transcribe -> cache."""
import argparse
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse, parse_qsl, urlencode, urlunparse

TRACKING_PARAMS = frozenset({
    "si", "feature", "utm_source", "utm_medium", "utm_campaign",
    "utm_term", "utm_content", "fbclid", "gclid", "igsh", "ref",
})


def is_url(source: str) -> bool:
    return source.startswith(("http://", "https://"))


def _normalize_url(url: str) -> str:
    p = urlparse(url)
    q = [(k, v) for k, v in parse_qsl(p.query) if k not in TRACKING_PARAMS]
    return urlunparse((p.scheme, p.netloc.lower(), p.path.rstrip("/"), "", urlencode(q), ""))


def cache_key(source: str) -> str:
    if is_url(source):
        return hashlib.sha256(_normalize_url(source).encode()).hexdigest()
    h = hashlib.sha256()
    with open(source, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def cache_dir() -> Path:
    base = os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache")
    return Path(base) / "audio-tldr"


class DownloadError(Exception):
    pass


def download_audio(url: str, workdir: Path):
    if not shutil.which("yt-dlp"):
        raise DownloadError(
            "yt-dlp not found — install with: pip install yt-dlp (or brew install yt-dlp)")
    probe = subprocess.run(
        ["yt-dlp", "--no-warnings", "--dump-json", "--no-download", "--no-playlist", url],
        capture_output=True, text=True, timeout=120,
    )
    if probe.returncode != 0:
        raise DownloadError(f"yt-dlp probe failed: {probe.stderr.strip()[:300]}")
    title = json.loads(probe.stdout).get("title", "untitled")
    safe = "".join(c for c in title if c.isalnum() or c in " -_")[:80] or "audio"
    out = workdir / f"{safe}.mp3"
    dl = subprocess.run(
        ["yt-dlp", "--no-warnings", "-x", "--audio-format", "mp3",
         "-o", str(out), "--no-playlist", url],
        capture_output=True, text=True, timeout=1800,
    )
    if dl.returncode != 0:
        raise DownloadError(f"yt-dlp download failed: {dl.stderr.strip()[:300]}")
    if not out.exists():
        found = sorted(workdir.glob("*.mp3"))
        if not found:
            raise DownloadError("yt-dlp finished but no mp3 produced")
        out = found[0]
    return str(out), title


def _module_available(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def detect_backend():
    if _module_available("mlx_whisper"):
        return "mlx-whisper"
    if _module_available("faster_whisper"):
        return "faster-whisper"
    cpp_model = os.environ.get("AUDIO_TLDR_WHISPER_CPP_MODEL", "")
    if shutil.which("whisper-cli") and cpp_model and Path(cpp_model).exists():
        return "whisper-cpp"
    if shutil.which("whisper"):
        return "openai-whisper"
    return None


def load_cached(key: str):
    meta_path = cache_dir() / key / "meta.json"
    try:
        meta = json.loads(meta_path.read_text())
        if Path(meta["transcript_path"]).exists():
            return meta
    except (OSError, ValueError, KeyError):
        pass
    return None


# ── Cache management ────────────────────────────────────────────────
# Retention is opt-in: no config -> nothing is ever auto-deleted.
def config_path() -> Path:
    return cache_dir() / "config.json"


def load_config() -> dict:
    try:
        return json.loads(config_path().read_text())
    except (OSError, ValueError):
        return {}


def save_config(cfg: dict):
    cache_dir().mkdir(parents=True, exist_ok=True)
    config_path().write_text(json.dumps(cfg))


def _iter_entries():
    d = cache_dir()
    if not d.exists():
        return
    for sub in sorted(d.iterdir()):
        if sub.is_dir() and (sub / "meta.json").exists():
            yield sub


def prune_expired() -> int:
    """Delete entries older than the configured retention. No config -> no-op."""
    days = load_config().get("retention_days")
    if not days:
        return 0
    cutoff = time.time() - days * 86400
    n = 0
    for sub in list(_iter_entries()):
        if (sub / "meta.json").stat().st_mtime < cutoff:
            shutil.rmtree(sub, ignore_errors=True)
            n += 1
    return n


def cmd_cache_info() -> int:
    entries, total = [], 0
    for sub in _iter_entries():
        try:
            meta = json.loads((sub / "meta.json").read_text())
        except ValueError:
            meta = {}
        size = sum(f.stat().st_size for f in sub.rglob("*") if f.is_file())
        total += size
        entries.append({
            "key": sub.name[:12],
            "title": meta.get("title", ""),
            "source": meta.get("source", ""),
            "cached_date": datetime.fromtimestamp(
                (sub / "meta.json").stat().st_mtime).strftime("%Y-%m-%d %H:%M"),
            "size_bytes": size,
        })
    print(json.dumps({
        "cache_dir": str(cache_dir()),
        "entries": entries,
        "total_bytes": total,
        "retention_days": load_config().get("retention_days"),
    }, ensure_ascii=False))
    return 0


def cmd_clear(source: str) -> int:
    target = None
    try:
        target = cache_dir() / cache_key(source)
    except OSError:
        pass  # local file no longer exists -> fall back to meta.source match
    if target is None or not target.exists():
        for sub in _iter_entries():
            try:
                if json.loads((sub / "meta.json").read_text()).get("source") == source:
                    target = sub
                    break
            except ValueError:
                continue
    if target is not None and target.exists():
        shutil.rmtree(target, ignore_errors=True)
        print(f"cleared: {source}")
    else:
        print(f"no cache entry for: {source}")
    return 0


def cmd_clear_all(confirmed: bool) -> int:
    if not confirmed:
        print("refusing to clear all cached transcripts without --yes", file=sys.stderr)
        return 2
    n = 0
    for sub in list(_iter_entries()):
        shutil.rmtree(sub, ignore_errors=True)
        n += 1
    print(f"cleared {n} entries")
    return 0


def cmd_set_retention(value: str) -> int:
    cfg = load_config()
    if value.lower() in ("off", "0", "none"):
        cfg.pop("retention_days", None)
        save_config(cfg)
        print("retention disabled — cache is kept forever")
        return 0
    try:
        days = int(value)
        if days <= 0:
            raise ValueError
    except ValueError:
        print(f"invalid retention: {value!r} (positive integer days, or 'off')", file=sys.stderr)
        return 2
    cfg["retention_days"] = days
    save_config(cfg)
    print(f"retention set: cache entries older than {days} days are pruned on next run")
    return 0


# ── Chinese output normalization (optional) ─────────────────────────
# Whisper often emits Simplified Chinese. If the `opencc` package is installed,
# Chinese transcripts are converted (default config: s2tw -> Taiwan Traditional).
# Set AUDIO_TLDR_ZH_CONVERT=off to disable, or to any OpenCC config (s2t, s2twp, t2s, ...).
# No opencc installed -> transcripts are left untouched.
_ZH_PROMPT = "以下是用繁體中文記錄的對話內容。"
_OPENCC = None  # lazy: None=untried, False=unavailable/disabled


def _get_zh_converter():
    global _OPENCC
    if _OPENCC is None:
        cfg = os.environ.get("AUDIO_TLDR_ZH_CONVERT", "s2tw")
        if cfg.lower() in ("off", "0", "none"):
            _OPENCC = False
        else:
            try:
                import opencc
                _OPENCC = opencc.OpenCC(cfg)
            except Exception:
                _OPENCC = False
    return _OPENCC or None


def _maybe_to_traditional(text, language):
    conv = _get_zh_converter() if (language or "").lower().startswith("zh") else None
    return conv.convert(text) if conv and text else text


DEFAULT_MODELS = {
    "mlx-whisper": os.environ.get("AUDIO_TLDR_MODEL", "mlx-community/whisper-large-v3-turbo"),
    "faster-whisper": os.environ.get("AUDIO_TLDR_MODEL", "small"),
    "openai-whisper": os.environ.get("AUDIO_TLDR_MODEL", "small"),
}

INSTALL_GUIDE = """No whisper backend found. Install ONE of:
  Apple Silicon (fastest):  pip install mlx-whisper
  Cross-platform (GPU/CPU): pip install faster-whisper
  whisper.cpp:              brew install whisper-cpp  (then set AUDIO_TLDR_WHISPER_CPP_MODEL=/path/to/ggml-*.bin)
  Original OpenAI CLI:      pip install openai-whisper
Also required: yt-dlp + ffmpeg for URL sources."""


def _run_backend(backend, audio_path, language):
    # When zh conversion is active, bias models toward Traditional vocabulary.
    # Safe for non-Chinese audio (prompt does not affect en/ja/... generation).
    zh_prompt = _ZH_PROMPT if _get_zh_converter() else None
    if backend == "mlx-whisper":
        import mlx_whisper
        kw = {"path_or_hf_repo": DEFAULT_MODELS[backend]}
        if language:
            kw["language"] = language
        if zh_prompt:
            kw["initial_prompt"] = zh_prompt
        r = mlx_whisper.transcribe(audio_path, **kw)
        dur = r["segments"][-1]["end"] if r.get("segments") else 0.0
        return r["text"].strip(), dur, r.get("language", language or "")
    if backend == "faster-whisper":
        from faster_whisper import WhisperModel
        model = WhisperModel(DEFAULT_MODELS[backend])
        segments, info = model.transcribe(audio_path, language=language,
                                          initial_prompt=zh_prompt)
        segs = list(segments)
        text = " ".join(s.text.strip() for s in segs)
        dur = segs[-1].end if segs else 0.0
        return text, dur, info.language
    if backend == "whisper-cpp":
        workdir = tempfile.mkdtemp(prefix="audio-tldr-cpp-")
        try:
            wav = os.path.join(workdir, "audio.16k.wav")
            subprocess.run(["ffmpeg", "-y", "-i", audio_path, "-ar", "16000", "-ac", "1", wav],
                           capture_output=True, check=True)
            # whisper-cli defaults to English when -l is omitted; "auto" enables detection
            cmd = ["whisper-cli", "-m", os.environ["AUDIO_TLDR_WHISPER_CPP_MODEL"],
                   "-f", wav, "--output-txt", "--no-prints", "-l", language or "auto"]
            if zh_prompt:
                cmd += ["--prompt", zh_prompt]
            subprocess.run(cmd, capture_output=True, check=True, timeout=7200)
            return Path(wav + ".txt").read_text().strip(), 0.0, language or ""
        finally:
            shutil.rmtree(workdir, ignore_errors=True)
    if backend == "openai-whisper":
        outdir = tempfile.mkdtemp(prefix="audio-tldr-")
        try:
            cmd = ["whisper", audio_path, "--model", DEFAULT_MODELS[backend],
                   "--output_format", "txt", "--output_dir", outdir]
            if language:
                cmd += ["--language", language]
            if zh_prompt:
                cmd += ["--initial_prompt", zh_prompt]
            subprocess.run(cmd, capture_output=True, check=True, timeout=7200)
            txts = sorted(Path(outdir).glob("*.txt"))
            return txts[0].read_text().strip(), 0.0, language or ""
        finally:
            shutil.rmtree(outdir, ignore_errors=True)
    raise ValueError(f"unknown backend {backend}")


def main(argv=None):
    ap = argparse.ArgumentParser(description="audio-tldr transcription engine")
    ap.add_argument("source", nargs="?", help="URL or local audio/video file path")
    ap.add_argument("--language", default=None)
    ap.add_argument("--force", action="store_true", help="ignore cache, re-transcribe")
    ap.add_argument("--cache-info", action="store_true", help="list cached transcripts (JSON)")
    ap.add_argument("--clear", metavar="SOURCE", help="delete the cache entry for one source")
    ap.add_argument("--clear-all", action="store_true", help="delete ALL cache entries (needs --yes)")
    ap.add_argument("--yes", action="store_true", help="confirm --clear-all")
    ap.add_argument("--set-retention", metavar="DAYS",
                    help="auto-prune entries older than DAYS on each run; 'off' = keep forever (default)")
    args = ap.parse_args(argv)

    if args.cache_info:
        return cmd_cache_info()
    if args.clear:
        return cmd_clear(args.clear)
    if args.clear_all:
        return cmd_clear_all(args.yes)
    if args.set_retention:
        return cmd_set_retention(args.set_retention)

    if not args.source:
        ap.print_usage(sys.stderr)
        return 2
    if not is_url(args.source) and not Path(args.source).exists():
        print(f"source not found: {args.source}", file=sys.stderr)
        return 2

    prune_expired()  # no-op unless the user configured a retention
    key = cache_key(args.source)
    if not args.force:
        meta = load_cached(key)
        if meta:
            print(json.dumps({**meta, "cache_hit": True}, ensure_ascii=False))
            return 0

    backend = detect_backend()
    if backend is None:
        print(INSTALL_GUIDE, file=sys.stderr)
        return 3

    title = Path(args.source).stem
    audio_path = args.source
    tmpdir = None
    try:
        if is_url(args.source):
            tmpdir = tempfile.mkdtemp(prefix="audio-tldr-dl-")
            audio_path, title = download_audio(args.source, Path(tmpdir))
        text, duration, lang = _run_backend(backend, audio_path, args.language)
    except DownloadError as e:
        print(str(e), file=sys.stderr)
        return 2
    except subprocess.CalledProcessError as e:
        err = e.stderr or b""
        if isinstance(err, bytes):
            err = err.decode(errors="replace")
        print(f"backend {backend} failed: {err[:300]}", file=sys.stderr)
        return 2
    except Exception as e:  # backend python API failures (model load, OOM, ...)
        print(f"backend {backend} failed: {e}", file=sys.stderr)
        return 2
    finally:
        if tmpdir:
            shutil.rmtree(tmpdir, ignore_errors=True)

    text = _maybe_to_traditional(text, lang)
    d = cache_dir() / key
    d.mkdir(parents=True, exist_ok=True)
    t_path = d / "transcript.txt"
    t_path.write_text(text)
    meta = {"transcript_path": str(t_path), "title": title, "duration": duration,
            "language": lang, "backend": backend, "source": args.source}
    (d / "meta.json").write_text(json.dumps(meta, ensure_ascii=False))
    print(json.dumps({**meta, "cache_hit": False}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
