#!/usr/bin/env python3
"""audio-tldr transcription engine: download -> detect backend -> transcribe -> cache."""
import argparse
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
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


def _canonical_apple(url: str):
    """Apple episode URL -> slug/storefront-independent identity string.
    The path slug differs between a show-page resolution (show name) and a
    directly copied episode link (episode title), and the storefront segment
    varies by region — none of that changes which episode it is. Identity is
    (collection id, episode id) only. Returns None when there is no episode id
    (bare show page) or the URL is not Apple Podcasts."""
    ids = _apple_ids(url)
    if ids is None:
        return None
    coll, ep, _country = ids
    if coll and ep:
        return f"https://podcasts.apple.com/podcast/id{coll}?i={ep}"
    return None


def cache_key(source: str) -> str:
    if is_url(source):
        canon = _canonical_apple(source) or _normalize_url(source)
        return hashlib.sha256(canon.encode()).hexdigest()
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


# ── Python interpreter selection ────────────────────────────────────
# Backend detection only sees the *current* interpreter. On hosts where a
# whisper backend lives in another Python (e.g. Homebrew 3.12 while the agent
# invoked /usr/bin/python3), re-exec into the interpreter that has it instead
# of misreporting "no backend installed". Nothing is ever installed here.
_REEXEC_ENV = "AUDIO_TLDR_REEXECED"


def _module_backend_in(python: str) -> bool:
    try:
        r = subprocess.run(
            [python, "-c",
             "import importlib.util as i, sys; "
             "sys.exit(0 if (i.find_spec('mlx_whisper') or i.find_spec('faster_whisper')) else 1)"],
            capture_output=True, timeout=15)
        return r.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def _candidate_interpreters():
    cands = []
    env_py = os.environ.get("AUDIO_TLDR_PYTHON")
    if env_py:
        cands.append(env_py)
    cands += ["/opt/homebrew/bin/python3.13", "/opt/homebrew/bin/python3.12",
              "/opt/homebrew/bin/python3", "/usr/local/bin/python3"]
    for name in ("python3.13", "python3.12", "python3.11"):
        w = shutil.which(name)
        if w:
            cands.append(w)
    seen, out = set(), []
    for c in cands:
        if not Path(c).exists():
            continue
        p = os.path.realpath(c)
        if p not in seen:
            seen.add(p)
            out.append(c)
    return out


def _honor_explicit_python(raw_argv):
    """AUDIO_TLDR_PYTHON set -> always run under that interpreter (highest priority)."""
    env_py = os.environ.get("AUDIO_TLDR_PYTHON")
    if not env_py or os.environ.get(_REEXEC_ENV):
        return
    if Path(env_py).exists() and os.path.realpath(env_py) != os.path.realpath(sys.executable):
        os.environ[_REEXEC_ENV] = "1"
        os.execv(env_py, [env_py, os.path.abspath(__file__)] + list(raw_argv))


def _maybe_reexec(raw_argv):
    """No module backend here -> switch to a candidate interpreter that has one."""
    if os.environ.get(_REEXEC_ENV):
        return
    cur = os.path.realpath(sys.executable)
    for cand in _candidate_interpreters():
        if os.path.realpath(cand) == cur:
            continue
        if _module_backend_in(cand):
            os.environ[_REEXEC_ENV] = "1"
            print(f"note: whisper backend found in {cand}; switching interpreter "
                  f"(set AUDIO_TLDR_PYTHON to override)", file=sys.stderr)
            os.execv(cand, [cand, os.path.abspath(__file__)] + list(raw_argv))


def cmd_doctor() -> int:
    """Environment diagnosis: distinguish 'not installed' from 'installed in
    another Python' from 'importable but Metal blocked (sandbox)'."""
    import platform
    info = {
        "python": {"path": sys.executable, "version": platform.python_version()},
        "tools": {"yt_dlp": bool(shutil.which("yt-dlp")), "ffmpeg": bool(shutil.which("ffmpeg"))},
        "backends": {
            "mlx_whisper": _module_available("mlx_whisper"),
            "faster_whisper": _module_available("faster_whisper"),
            "whisper_cpp": bool(shutil.which("whisper-cli"))
                           and bool(os.environ.get("AUDIO_TLDR_WHISPER_CPP_MODEL")),
            "openai_whisper": bool(shutil.which("whisper")),
        },
        "opencc": _module_available("opencc"),
        "selected_backend": detect_backend(),
        "other_interpreters": [],
        "metal": None,
    }
    cur = os.path.realpath(sys.executable)
    for cand in _candidate_interpreters():
        if os.path.realpath(cand) == cur:
            continue
        info["other_interpreters"].append(
            {"path": cand, "module_backend": _module_backend_in(cand)})
    if _module_available("mlx_whisper"):
        try:
            r = subprocess.run(
                [sys.executable, "-c", "import mlx.core as mx; mx.default_device()"],
                capture_output=True, text=True, timeout=30)
            info["metal"] = {"available": r.returncode == 0,
                             "error": None if r.returncode == 0
                             else (r.stderr.strip()[-300:] or "Metal init failed")}
        except (OSError, subprocess.TimeoutExpired) as e:
            info["metal"] = {"available": False, "error": str(e)}
    print(json.dumps(info, ensure_ascii=False, indent=2))
    return 0


# ── Apple Podcasts fallback ─────────────────────────────────────────
# yt-dlp's ApplePodcasts extractor is flaky (observed HTTP 500 on valid pages).
# Fallback: episode id -> iTunes lookup -> public episodeUrl (or RSS enclosure).
# The enclosure is transport only — cache identity stays on the Apple URL.

def _apple_ids(url: str):
    p = urlparse(url)
    if p.netloc.lower() != "podcasts.apple.com":
        return None
    m = re.search(r"/id(\d+)", p.path)
    coll = m.group(1) if m else None
    ep = dict(parse_qsl(p.query)).get("i")
    # storefront country is the first path segment (/tw/podcast/...) — the
    # lookup API misses region-specific shows without it
    seg = p.path.strip("/").split("/", 1)[0]
    country = seg if len(seg) == 2 and seg.isalpha() else None
    return (coll, ep, country)


def _lookup_json(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "audio-tldr"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())


def _enclosure_from_feed(feed_url: str, title: str):
    try:
        req = urllib.request.Request(feed_url, headers={"User-Agent": "audio-tldr"})
        with urllib.request.urlopen(req, timeout=30) as r:
            xml_text = r.read().decode(errors="replace")
    except OSError:
        return None
    import xml.etree.ElementTree as ET
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return None
    for item in root.iter("item"):
        if (item.findtext("title") or "").strip() == title.strip():
            enc = item.find("enclosure")
            if enc is not None:
                return enc.get("url")
    return None


def _resolve_show_to_latest(source: str):
    """Apple show-page URL (no ?i=) -> (canonical latest-episode URL, episode title).
    Returns (source, None) for anything that is not an Apple show page.
    Rewriting happens BEFORE cache-key computation so the cache binds to the
    episode — next week the same show link resolves to the new latest episode
    instead of hitting a stale cache entry."""
    ids = _apple_ids(source)
    if ids is None:
        return source, None
    coll, ep, country = ids
    if ep or not coll:
        return source, None
    q = f"https://itunes.apple.com/lookup?id={coll}&entity=podcastEpisode&limit=200"
    if country:
        q += f"&country={country}"
    try:
        data = _lookup_json(q)
    except (OSError, ValueError) as e:
        raise DownloadError(f"Apple lookup failed: {e}")
    episodes = [r for r in data.get("results", [])
                if r.get("kind") != "podcast" and r.get("trackId")]
    if not episodes:
        raise DownloadError("Apple Podcasts: no episodes found for this show")
    latest = max(episodes, key=lambda r: r.get("releaseDate") or "")
    sep = "&" if "?" in source else "?"
    return f"{source}{sep}i={latest['trackId']}", latest.get("trackName") or "untitled"


def resolve_apple_podcast(url: str):
    """Apple Podcasts page URL -> (media_url, episode_title).
    Returns None for non-Apple URLs; raises DownloadError with a specific
    reason when an Apple URL cannot be resolved."""
    ids = _apple_ids(url)
    if ids is None:
        return None
    coll, ep, country = ids
    if not ep:
        raise DownloadError(
            "Apple Podcasts: this is a show page, not an episode link — open the "
            "episode and copy its link (it needs ?i=<episodeId>)")
    if not coll:
        raise DownloadError("Apple Podcasts: could not parse the show id from the URL")
    # Episode-id lookup returns 0 results even with a storefront; the reliable
    # path is collection lookup listing recent episodes, then matching trackId.
    q = f"https://itunes.apple.com/lookup?id={coll}&entity=podcastEpisode&limit=200"
    if country:
        q += f"&country={country}"
    try:
        data = _lookup_json(q)
    except (OSError, ValueError) as e:
        raise DownloadError(f"Apple lookup failed: {e}")
    hits = [r for r in data.get("results", []) if str(r.get("trackId")) == str(ep)]
    if not hits:
        raise DownloadError(
            "Apple lookup: episode not found in the show's recent episodes "
            "(removed, region-locked, subscriber-only, or older than the 200-episode "
            "lookup window — paste the episode's RSS/media URL directly instead)")
    r0 = hits[0]
    title = r0.get("trackName") or "untitled"
    media = r0.get("episodeUrl")
    if not media and r0.get("feedUrl"):
        media = _enclosure_from_feed(r0["feedUrl"], title)
    if not media:
        raise DownloadError(
            "Apple Podcasts: no public media URL for this episode "
            "(subscriber-only content cannot be fetched)")
    return media, title


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


# ── Repetition collapse ─────────────────────────────────────────────
# Whisper's decoder can loop on trailing silence/music, emitting the same
# phrase dozens of times (classic tail hallucination). Collapse runs of 3+
# consecutive identical phrases to one occurrence; 2 repeats are left alone
# (legit emphasis). Set AUDIO_TLDR_DEREPEAT=off to disable.
_REPEAT_RE = re.compile(r"(\S.{1,119}?)(?:\s*\1){2,}", re.S)


def _collapse_repetitions(text: str) -> str:
    if not text or os.environ.get("AUDIO_TLDR_DEREPEAT", "").lower() in ("off", "0", "none"):
        return text
    for _ in range(10):  # fixpoint: nested loops (ABAB ABAB) need re-passes
        collapsed = _REPEAT_RE.sub(r"\1", text)
        if collapsed == text:
            break
        text = collapsed
    return text


# ── Chinese output normalization (optional) ─────────────────────────
# Whisper often emits Simplified Chinese. If the `opencc` package is installed,
# Chinese transcripts are converted (default config: s2twp -> Taiwan Traditional
# incl. common-phrase localization, e.g. 軟件->軟體).
# Set AUDIO_TLDR_ZH_CONVERT=off to disable, or to any OpenCC config (s2t, s2twp, t2s, ...).
# No opencc installed -> transcripts are left untouched.
_ZH_PROMPT = "以下是用繁體中文記錄的對話內容。"
_OPENCC = None  # lazy: None=untried, False=unavailable/disabled


def _get_zh_converter():
    global _OPENCC
    if _OPENCC is None:
        cfg = os.environ.get("AUDIO_TLDR_ZH_CONVERT", "s2twp")
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


DEFAULT_MODEL = "large-v3-turbo"


def resolve_model(backend: str, cli_model):
    """Pick the whisper model: --model > AUDIO_TLDR_MODEL env > large-v3-turbo.
    Accepts canonical names (large-v3-turbo), whisper-prefixed names
    (whisper-large-v3-turbo), or a full HF repo path (kept as-is). mlx needs a
    repo path, so bare names get the mlx-community/whisper- prefix; the other
    backends take canonical names directly. whisper-cpp ignores this entirely
    (its model is the AUDIO_TLDR_WHISPER_CPP_MODEL file)."""
    name = cli_model or os.environ.get("AUDIO_TLDR_MODEL") or DEFAULT_MODEL
    if "/" in name:
        return name
    if name.startswith("whisper-"):
        name = name[len("whisper-"):]
    if backend == "mlx-whisper":
        return f"mlx-community/whisper-{name}"
    return name

INSTALL_GUIDE = """No whisper backend found. Install ONE of:
  Apple Silicon (fastest):  pip install mlx-whisper
  Cross-platform (GPU/CPU): pip install faster-whisper
  whisper.cpp:              brew install whisper-cpp  (then set AUDIO_TLDR_WHISPER_CPP_MODEL=/path/to/ggml-*.bin)
  Original OpenAI CLI:      pip install openai-whisper
Also required: yt-dlp + ffmpeg for URL sources."""


def _run_backend(backend, audio_path, language, model_name=None):
    # When zh conversion is active, bias models toward Traditional vocabulary.
    # Safe for non-Chinese audio (prompt does not affect en/ja/... generation).
    zh_prompt = _ZH_PROMPT if _get_zh_converter() else None
    model_id = resolve_model(backend, model_name)
    if backend == "mlx-whisper":
        import mlx_whisper
        kw = {"path_or_hf_repo": model_id}
        if language:
            kw["language"] = language
        if zh_prompt:
            kw["initial_prompt"] = zh_prompt
        r = mlx_whisper.transcribe(audio_path, **kw)
        dur = r["segments"][-1]["end"] if r.get("segments") else 0.0
        return r["text"].strip(), dur, r.get("language", language or "")
    if backend == "faster-whisper":
        from faster_whisper import WhisperModel
        model = WhisperModel(model_id)
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
            cmd = ["whisper", audio_path, "--model", model_id,
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
    raw_argv = list(argv) if argv is not None else sys.argv[1:]
    _honor_explicit_python(raw_argv)
    ap = argparse.ArgumentParser(description="audio-tldr transcription engine")
    ap.add_argument("source", nargs="?", help="URL or local audio/video file path")
    ap.add_argument("--language", default=None)
    ap.add_argument("--model", default=None,
                    help="whisper model (default: large-v3-turbo; also via AUDIO_TLDR_MODEL). "
                         "Bare names map per backend (mlx gets the mlx-community/ prefix); "
                         "a full HF repo path is used as-is. Ignored by whisper-cpp")
    ap.add_argument("--force", action="store_true", help="ignore cache, re-transcribe")
    ap.add_argument("--cache-info", action="store_true", help="list cached transcripts (JSON)")
    ap.add_argument("--clear", metavar="SOURCE", help="delete the cache entry for one source")
    ap.add_argument("--clear-all", action="store_true", help="delete ALL cache entries (needs --yes)")
    ap.add_argument("--yes", action="store_true", help="confirm --clear-all")
    ap.add_argument("--set-retention", metavar="DAYS",
                    help="auto-prune entries older than DAYS on each run; 'off' = keep forever (default)")
    ap.add_argument("--keep-audio", action="store_true",
                    help="keep the downloaded audio in the cache entry instead of deleting it (URL sources)")
    ap.add_argument("--doctor", action="store_true",
                    help="diagnose the environment (python, backends, tools, other interpreters, Metal) as JSON")
    args = ap.parse_args(raw_argv)

    if args.doctor:
        return cmd_doctor()
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

    if is_url(args.source):
        try:
            new_src, latest_title = _resolve_show_to_latest(args.source)
        except DownloadError as e:
            print(str(e), file=sys.stderr)
            return 2
        if new_src != args.source:
            print(f"note: Apple Podcasts show page → using the latest episode: {latest_title}",
                  file=sys.stderr)
            args.source = new_src

    prune_expired()  # no-op unless the user configured a retention
    key = cache_key(args.source)
    if not args.force:
        meta = load_cached(key)
        if meta:
            if args.keep_audio and not meta.get("audio_path"):
                print("note: --keep-audio ignored on cache hit (transcript already cached; "
                      "re-run with --force to download and keep the audio)", file=sys.stderr)
            print(json.dumps({**meta, "cache_hit": True}, ensure_ascii=False))
            return 0

    backend = detect_backend()
    if backend is None:
        _maybe_reexec(raw_argv)  # switches interpreter (never returns) if one has a backend
        print(INSTALL_GUIDE, file=sys.stderr)
        print("tip: run --doctor to see which interpreters/tools were probed",
              file=sys.stderr)
        return 3

    title = Path(args.source).stem
    audio_path = args.source
    tmpdir = None
    kept_audio = None
    media_url = None
    d = cache_dir() / key
    try:
        if is_url(args.source):
            tmpdir = tempfile.mkdtemp(prefix="audio-tldr-dl-")
            try:
                audio_path, title = download_audio(args.source, Path(tmpdir))
            except DownloadError:
                resolved = resolve_apple_podcast(args.source)
                if resolved is None:
                    raise
                media_url, ep_title = resolved
                print("note: Apple Podcasts extractor failed; falling back to the "
                      "episode's public media URL (cache identity stays on the Apple link)",
                      file=sys.stderr)
                audio_path, dl_title = download_audio(media_url, Path(tmpdir))
                title = ep_title or dl_title
        text, duration, lang = _run_backend(backend, audio_path, args.language, args.model)
        if args.keep_audio and tmpdir:
            # Audio retention is an optional side-effect: its failure must never
            # discard the (potentially expensive) transcription that already succeeded.
            try:
                d.mkdir(parents=True, exist_ok=True)
                kept_audio = d / "audio.mp3"
                shutil.move(audio_path, kept_audio)
            except OSError as e:
                print(f"warning: could not keep audio ({e}); continuing without it",
                      file=sys.stderr)
                kept_audio = None
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

    deduped = _collapse_repetitions(text)
    if deduped != text:
        print(f"note: collapsed repeated phrases ({len(text) - len(deduped)} chars removed — "
              f"likely whisper tail hallucination; AUDIO_TLDR_DEREPEAT=off to disable)",
              file=sys.stderr)
        text = deduped
    text = _maybe_to_traditional(text, lang)
    d.mkdir(parents=True, exist_ok=True)
    t_path = d / "transcript.txt"
    t_path.write_text(text)
    model_used = (os.environ.get("AUDIO_TLDR_WHISPER_CPP_MODEL", "")
                  if backend == "whisper-cpp" else resolve_model(backend, args.model))
    meta = {"transcript_path": str(t_path), "title": title, "duration": duration,
            "language": lang, "backend": backend, "model": model_used,
            "source": args.source}
    if media_url:
        meta["media_url"] = media_url  # transport URL actually fetched (Apple fallback)
    if kept_audio is None and (d / "audio.mp3").exists():
        # Previously kept audio (e.g. a --force re-run without --keep-audio):
        # never delete user-kept data, keep referencing it instead of orphaning it.
        kept_audio = d / "audio.mp3"
    if kept_audio is not None:
        meta["audio_path"] = str(kept_audio)
    (d / "meta.json").write_text(json.dumps(meta, ensure_ascii=False))
    print(json.dumps({**meta, "cache_hit": False}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
