#!/usr/bin/env python3
"""audio-tldr transcription engine: download -> detect backend -> transcribe -> cache."""
import argparse
import hashlib
import importlib.util
import json
import locale
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Optional
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


# ── Cache entry schema (v1.0) ───────────────────────────────────────
# Files are always looked up inside the entry folder by these fixed names.
# meta.json's absolute *_path values are kept (and refreshed) only so that
# v0.9.x can still read an entry after a downgrade; v1 never reads them,
# so a copied cache cannot reach back into the old folder and a tampered
# meta.json cannot point outside its own entry.
SCHEMA_VERSION = 1
ENTRY_FILES = {
    "transcript": "transcript.txt",
    "segments": "segments.json",
    "srt": "transcript.srt",
    "vtt": "transcript.vtt",
    "audio": "audio.mp3",
}
PATH_KEYS = {
    "transcript": "transcript_path",
    "segments": "segments_path",
    "srt": "srt_path",
    "vtt": "vtt_path",
    "audio": "audio_path",
}
V1_ONLY_KEYS = ("schema_version", "cached_date", "files")

# Files correct.py derives from the transcript. Kept out of ENTRY_FILES on
# purpose: those are recorded in meta["files"] and promised to hit on every
# 1.x (internal ADR); these are recomputable (internal ADR).
DERIVED_FILES = {
    "corrected": "transcript.corrected.txt",
    "corrected_srt": "transcript.corrected.srt",
    "corrected_vtt": "transcript.corrected.vtt",
    "corrections": "corrections.json",
    "reference": "reference.md",
    "usage": "usage.jsonl",
}
# History, not a derivative of the transcript: a fresh transcription keeps it.
KEPT_ON_RETRANSCRIBE = {"usage"}


def derived_file(d: Path, name: str) -> Path:
    return Path(d) / DERIVED_FILES[name]


USAGE_FIELDS = ("v", "date", "phase", "path", "model", "provider", "fallback", "input",
                "cache_write", "cache_read", "output", "total", "source")


def append_usage(d: Path, data: dict) -> None:
    """One line in usage.jsonl: whitelisted fields only, anything unreported stays null."""
    row = {k: data.get(k) for k in USAGE_FIELDS}
    row["v"] = 1
    row["date"] = row["date"] or datetime.now(timezone.utc).isoformat()
    with open(derived_file(d, "usage"), "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


# ── Line breaks (v1.0 item 5) ───────────────────────────────────────
# transcript.txt used to be one line: a coding agent's file reader pages by
# line, so a long single-line transcript was read only up to its first ~20k
# characters. One Whisper segment per line; a line longer than LINE_MAX is
# cut at a sentence end, a comma or a space. Only "\n" is ever inserted.
LINE_MAX = 400
LINE_MIN_BREAK = 200
_SENT_END = "。！？!?…"
_CLOSERS = "」』”’）)]】"
_SOFT_BREAKS = "，、,;；：:"
_LOCATE_SLACK = 50


def strip_breaks(text: str) -> str:
    return text.replace("\r", "").replace("\n", "")


def segment_ends(text: str, segments, convert=None) -> list:
    """Positions in `text` just after each segment that can be found, in order.
    Post-processing (de-repetition, zh conversion) changed some segments, so each
    is tried as stored and converted; a segment that cannot be found is skipped and
    its length widens the window for the next one."""
    ends, pos, skipped = [], 0, 0
    for seg in segments or []:
        st = (seg.get("text") or "").strip() if isinstance(seg, dict) else ""
        if not st:
            continue
        cands = [st]
        if convert:
            c = convert(st)
            if c and c != st:
                cands.append(c)
        for cand in cands:
            j = text.find(cand, pos)
            if j >= 0 and j - pos <= skipped + _LOCATE_SLACK:
                pos = j + len(cand)
                ends.append(pos)
                skipped = 0
                break
        else:
            skipped += len(st)
    return ends


def _is_ascii_alnum(c: str) -> bool:
    return c.isascii() and c.isalnum()


def _long_line_cuts(line: str) -> list:
    """Cut offsets inside one line longer than LINE_MAX."""
    cuts, start = [], 0
    while len(line) - start > LINE_MAX:
        cut = None
        for cls in (_SENT_END, _SOFT_BREAKS, " "):
            for k in range(start + LINE_MIN_BREAK, start + LINE_MAX):
                if line[k - 1] in cls:
                    if cls is _SENT_END:
                        while k < min(len(line) - 1, start + LINE_MAX) and line[k] in _CLOSERS:
                            k += 1
                    cut = k
                    break
            if cut:
                break
        if cut is None:
            k = start + LINE_MAX
            while k > start + LINE_MIN_BREAK and _is_ascii_alnum(line[k - 1]) and _is_ascii_alnum(line[k]):
                k -= 1
            cut = k if k > start + LINE_MIN_BREAK else start + LINE_MAX
        cuts.append(cut)
        start = cut
    return cuts


def wrap_lines(text: str, segments=None, convert=None) -> str:
    """One segment per line, long lines cut; inserts "\\n" only (never inside "\\r\\n")."""
    if not text:
        return text
    lines = text.split("\n")
    if len(lines) > 1 and all(len(l.rstrip("\r")) <= LINE_MAX for l in lines):
        return text
    ins = set()
    for b in segment_ends(text, segments, convert):
        if b < len(text) and text[b] == " ":  # faster-whisper joins segments with a space:
            b += 1                             # keep it at the end of the line, not the start
        if 0 < b < len(text) and text[b] not in "\r\n" and text[b - 1] not in "\r\n":
            ins.add(b)
    bounds = sorted(ins | {i + 1 for i, c in enumerate(text) if c == "\n"} | {0, len(text)})
    for a, b in zip(bounds, bounds[1:]):
        body = text[a:b].rstrip("\r\n")
        if len(body) > LINE_MAX:
            ins.update(a + c for c in _long_line_cuts(body) if text[a + c - 1] != "\r")
    out, prev = [], 0
    for p in sorted(ins):
        out.append(text[prev:p])
        prev = p
    out.append(text[prev:])
    return "\n".join(out)


def tail_of(text: str, n: int = 12) -> str:
    """The last n non-whitespace characters of the text, taken across line breaks. (Not "the
    last line": real transcripts often end in a line of a few characters, and a file that is
    still one line would give its start.)"""
    return "".join(text.split())[-n:]


def remove_correction_files(d: Path) -> None:
    """A fresh transcription makes any corrected copy stale."""
    for name in DERIVED_FILES:
        if name in KEPT_ON_RETRANSCRIBE:
            continue
        try:
            derived_file(d, name).unlink()
        except FileNotFoundError:
            pass
        except OSError as e:
            print(f"warning: could not remove {derived_file(d, name)}: {e}", file=sys.stderr)

REPLACE_RETRIES = 5
REPLACE_RETRY_DELAY = 0.1


def resolve_entry_file(d: Path, name: str) -> Optional[Path]:
    p = d / ENTRY_FILES[name]
    return p if p.exists() else None


def _read_text(path: Path) -> str:
    """Text of a file, trying UTF-8 (with or without BOM) first, then the system
    code page, which is what v0.9.x wrote with on Windows (cp950 on a Traditional
    Chinese system). locale.getencoding() ignores Python's UTF-8 mode, so it still
    names the ANSI code page there. Raises OSError, or the last UnicodeDecodeError
    when no encoding fits; callers that must not crash catch it."""
    raw = path.read_bytes()
    getenc = getattr(locale, "getencoding", None)
    system = getenc() if getenc else locale.getpreferredencoding(False)
    tried = []
    err = None
    for enc in ("utf-8-sig", "utf-8", system):
        if enc in tried:
            continue
        tried.append(enc)
        try:
            return raw.decode(enc)
        except UnicodeDecodeError as e:
            err = e
        except LookupError:
            continue
    if err is None:
        raise UnicodeDecodeError("utf-8", raw, 0, 1, "no usable encoding")
    raise err


def _read_json(path: Path):
    """Parsed JSON, or None if missing/unreadable (see _read_text for encodings)."""
    try:
        return json.loads(_read_text(path))
    except (OSError, ValueError):
        return None


def _atomic_write_text(path: Path, text: str, mtime_ns: Optional[int] = None,
                       newline: Optional[str] = None) -> None:
    """Write via a temp file in the same folder and os.replace, so a concurrent
    reader sees the old file or the new one, never half of either. The mtime is
    set after the temp file is closed: Windows updates it on close."""
    tmp = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    try:
        with open(tmp, "w", encoding="utf-8", newline=newline) as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        if mtime_ns is not None:
            os.utime(tmp, ns=(time.time_ns(), mtime_ns))
        for attempt in range(REPLACE_RETRIES):
            try:
                os.replace(tmp, path)
                return
            except PermissionError:
                if attempt == REPLACE_RETRIES - 1:
                    raise
                time.sleep(REPLACE_RETRY_DELAY)
    except BaseException:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise


def entry_cached_ts(d: Path, meta: dict) -> float:
    """When the entry was transcribed: cached_date (v1) -> created (frames-only
    entries; naive = local time) -> meta.json's mtime (v0)."""
    for key in ("cached_date", "created"):
        raw = meta.get(key)
        if isinstance(raw, str):
            try:
                dt = datetime.fromisoformat(raw)
            except ValueError:
                continue
            if dt.tzinfo is None:
                dt = dt.astimezone()
            return dt.timestamp()
    return (d / "meta.json").stat().st_mtime


def _same_path(a, b) -> bool:
    norm = lambda p: os.path.normcase(os.path.realpath(str(p)))
    return norm(a) == norm(b)


def upgrade_meta(d: Path, meta: dict) -> dict:
    """meta in the v1 shape, with every *_path it already had pointing at this
    folder. Keys are refreshed or dropped, never added: stdout's key set must
    stay what v0.9.1 printed."""
    new = dict(meta)
    if not isinstance(new.get("cached_date"), str):
        new["cached_date"] = datetime.fromtimestamp(
            entry_cached_ts(d, meta), timezone.utc).isoformat()
    for name, key in PATH_KEYS.items():
        if key in new:
            p = resolve_entry_file(d, name)
            if p is None:
                new.pop(key)
            else:
                new[key] = str(p)
    new["files"] = {n: f for n, f in ENTRY_FILES.items() if resolve_entry_file(d, n)}
    new["schema_version"] = SCHEMA_VERSION
    return new


def _needs_rewrite(d: Path, meta: dict) -> bool:
    if meta.get("schema_version", 0) < SCHEMA_VERSION:
        return True
    for name, key in PATH_KEYS.items():
        if key in meta:
            p = resolve_entry_file(d, name)
            if p is None or not _same_path(meta[key], p):
                return True
    return False


def public_meta(d: Path, meta: dict) -> dict:
    out = {k: v for k, v in meta.items() if k not in V1_ONLY_KEYS}
    for name, key in PATH_KEYS.items():
        if key in out:
            p = resolve_entry_file(d, name)
            if p is None:
                out.pop(key)
            else:
                out[key] = str(p)
    return out


class DownloadError(Exception):
    pass


YTDLP_MISSING = ("yt-dlp not found — install it into this Python with: pip install yt-dlp "
                 "(Windows: py -3 -m pip install yt-dlp; or brew install yt-dlp). A yt-dlp.cmd "
                 "or .bat shim is not used")


def ytdlp_command(windows=None):
    """How to launch yt-dlp, as an argv prefix, or None when there is no safe way.

    The bare name "yt-dlp" is never used: on Windows, CreateProcess then looks
    for yt-dlp.exe only. On Windows the Python module comes first — a signed
    python.exe running -m yt_dlp is allowed where Smart App Control blocks the
    unsigned yt-dlp.exe. Elsewhere the executable comes first (a Homebrew
    yt-dlp is usually newer than a stray pip copy). A .cmd/.bat is never run:
    it goes through cmd.exe, where an & in a URL (...&t=30) splits the
    command line, so a crafted link could run a second command."""
    if windows is None:
        windows = os.name == "nt"
    module = [sys.executable, "-m", "yt_dlp"] if _module_available("yt_dlp") else None
    found = shutil.which("yt-dlp")
    exe = [found] if found and Path(found).suffix.lower() not in (".cmd", ".bat") else None
    order = (module, exe) if windows else (exe, module)
    return next((c for c in order if c), None)


def download_audio(url: str, workdir: Path):
    ytdlp = ytdlp_command()
    if not ytdlp:
        raise DownloadError(YTDLP_MISSING)
    probe = subprocess.run(
        [*ytdlp, "--no-warnings", "--dump-json", "--no-download", "--no-playlist", url],
        capture_output=True, text=True, timeout=120,
    )
    if probe.returncode != 0:
        raise DownloadError(f"yt-dlp probe failed: {probe.stderr.strip()[:300]}")
    info = json.loads(probe.stdout)
    title = info.get("title", "untitled")
    safe = "".join(c for c in title if c.isalnum() or c in " -_")[:80] or "audio"
    out = workdir / f"{safe}.mp3"
    dl = subprocess.run(
        [*ytdlp, "--no-warnings", "-x", "--audio-format", "mp3",
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
    return str(out), title, info


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


def _modules_in(python: str, mods) -> dict:
    """Which of `mods` another interpreter can import (all False if it won't run)."""
    code = ("import importlib.util as i, json; "
            f"print(json.dumps({{m: bool(i.find_spec(m)) for m in {list(mods)!r}}}))")
    try:
        r = subprocess.run([python, "-c", code], capture_output=True, text=True, timeout=15)
        found = json.loads(r.stdout) if r.returncode == 0 else {}
    except (OSError, subprocess.TimeoutExpired, ValueError):
        found = {}
    return {m: bool(found.get(m)) for m in mods}


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


_IS_WINDOWS = os.name == "nt"


def utf8_stdio():
    """Print UTF-8 whatever the console code page is. Without PYTHONUTF8, Python on
    Windows writes stdout in the ANSI code page (cp950 on Traditional Chinese
    systems), and the JSON every script prints (ensure_ascii=False) reached the
    agent as mojibake (2026-10-11 Windows run). Called once at each script entry."""
    for stream in (sys.stdout, sys.stderr):
        enc = (getattr(stream, "encoding", None) or "").lower().replace("-", "")
        if enc != "utf8" and hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8")
            except (ValueError, OSError):
                pass


def _reexec_into(python, script, raw_argv):
    """Run `script` under another interpreter and end this process.

    POSIX: os.execv replaces the process, so the caller sees the new one's output.
    Windows: os.execv starts a child and ends the parent at once — the caller gets
    empty stdout and exit 0 while the child prints later (2026-10-11 real-path
    run). Run the child, wait, and pass its exit code back instead."""
    argv = [python, script] + list(raw_argv)
    if _IS_WINDOWS:
        sys.stdout.flush()
        sys.stderr.flush()
        sys.exit(subprocess.run(argv).returncode)
    os.execv(python, argv)


def _honor_explicit_python(raw_argv):
    """AUDIO_TLDR_PYTHON set -> always run under that interpreter (highest priority)."""
    env_py = os.environ.get("AUDIO_TLDR_PYTHON")
    if not env_py or os.environ.get(_REEXEC_ENV):
        return
    if Path(env_py).exists() and os.path.realpath(env_py) != os.path.realpath(sys.executable):
        os.environ[_REEXEC_ENV] = "1"
        _reexec_into(env_py, os.path.abspath(__file__), raw_argv)


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
            _reexec_into(cand, os.path.abspath(__file__), raw_argv)


def cmd_doctor() -> int:
    """Environment diagnosis: distinguish 'not installed' from 'installed in
    another Python' from 'importable but Metal blocked (sandbox)'."""
    launcher = ytdlp_command()
    import platform
    info = {
        "python": {"path": sys.executable, "version": platform.python_version()},
        "tools": {"yt_dlp": bool(launcher), "yt_dlp_launcher": launcher,
                  "ffmpeg": bool(shutil.which("ffmpeg"))},
        "backends": {
            "mlx_whisper": _module_available("mlx_whisper"),
            "faster_whisper": _module_available("faster_whisper"),
            "whisper_cpp": bool(shutil.which("whisper-cli"))
                           and bool(os.environ.get("AUDIO_TLDR_WHISPER_CPP_MODEL")),
            "openai_whisper": bool(shutil.which("whisper")),
        },
        "opencc": _module_available("opencc"),
        "pypinyin": _module_available("pypinyin"),
        "jellyfish": _module_available("jellyfish"),
        "selected_backend": detect_backend(),
        "other_interpreters": [],
        "metal": None,
    }
    cur = os.path.realpath(sys.executable)
    for cand in _candidate_interpreters():
        if os.path.realpath(cand) == cur:
            continue
        info["other_interpreters"].append(
            {"path": cand, "module_backend": _module_backend_in(cand),
             **_modules_in(cand, ("pypinyin", "jellyfish"))})
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


def _apple_episode(url: str):
    """Apple Podcasts episode URL -> its iTunes lookup result, or None for a
    non-Apple URL. Raises DownloadError with a specific reason otherwise."""
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
    return hits[0]


def resolve_apple_podcast(url: str):
    """Apple Podcasts page URL -> (media_url, episode_title, context).
    Returns None for non-Apple URLs; raises DownloadError with a specific
    reason when an Apple URL cannot be resolved."""
    r0 = _apple_episode(url)
    if r0 is None:
        return None
    title = r0.get("trackName") or "untitled"
    media = r0.get("episodeUrl")
    if not media and r0.get("feedUrl"):
        media = _enclosure_from_feed(r0["feedUrl"], title)
    if not media:
        raise DownloadError(
            "Apple Podcasts: no public media URL for this episode "
            "(subscriber-only content cannot be fetched)")
    return media, title, apple_context(r0)


def upgrade_transcript_lines(d: Path, meta: dict) -> bool:
    """v1.0 item 5: a single-line transcript cached before 1.0 gets line breaks
    inserted (nothing else changes; ADR-0005). Gives up quietly on any doubt;
    no exception escapes, so a cache hit is never blocked by the upgrade."""
    try:
        t = resolve_entry_file(d, "transcript")
        if t is None:
            return False
        raw = t.read_bytes()
        if raw.startswith(b"\xef\xbb\xbf"):
            return False  # BOM: rewriting as plain UTF-8 would drop it
        try:
            text = raw.decode("utf-8")  # strict: legacy code pages are left alone
        except UnicodeDecodeError:
            return False
        if all(len(l.rstrip("\r")) <= LINE_MAX for l in text.split("\n")):
            return False
        segs = None
        seg_path = resolve_entry_file(d, "segments")
        if seg_path is not None:
            segs = _read_json(seg_path)
            segs = segs if isinstance(segs, list) else None
        lang = meta.get("language") or ""
        new = wrap_lines(text, segs, lambda s: _maybe_to_traditional(s, lang))
        if new == text or strip_breaks(new) != strip_breaks(text):
            return False
        if hashlib.sha256(t.read_bytes()).digest() != hashlib.sha256(raw).digest():
            return False  # another process rewrote it (e.g. --force) since we read it
        _atomic_write_text(t, new, mtime_ns=t.stat().st_mtime_ns, newline="")
    except Exception as e:
        print(f"note: could not add line breaks to the cached transcript ({e}); using it as is",
              file=sys.stderr)
        return False
    return True


def load_cached(key: str):
    d = cache_dir() / key
    meta_path = d / "meta.json"
    meta = _read_json(meta_path)
    if not isinstance(meta, dict) or resolve_entry_file(d, "transcript") is None:
        return None
    if "transcript_path" not in meta or meta.get("frames_only"):
        return None  # frames-only stub (frames.py): no transcript was recorded
    version = meta.get("schema_version", 0)
    if not isinstance(version, int) or isinstance(version, bool):
        return None
    if version > SCHEMA_VERSION:
        return meta  # written by a newer version: read, never rewrite
    if _needs_rewrite(d, meta):
        new = upgrade_meta(d, meta)
        try:
            _atomic_write_text(meta_path, json.dumps(new),
                               mtime_ns=meta_path.stat().st_mtime_ns)
        except OSError as e:
            print(f"note: could not update cache entry metadata ({e}); using it as is",
                  file=sys.stderr)
        meta = new
    upgrade_transcript_lines(d, meta)
    return meta


# ── Source context for name correction (v0.9.0) ─────────────────────
# Whisper cannot tell 真真 from 珍珍: they sound identical. The source's own
# metadata (title, channel, description, chapters, tags) usually spells the
# names right, so it is kept next to the transcript for the digest step to
# check spellings against. Extraction only — nothing here decides anything.
CONTEXT_DESCRIPTION_MAX = 4000
CONTEXT_CHAPTERS_MAX = 50
CONTEXT_TAGS_MAX = 30
CONTEXT_CREATOR_MAX = 200
CONTEXT_RETRY_DAYS = 7
CONTEXT_FETCH_TIMEOUT = 30


def _clean_str(value):
    return value.strip() if isinstance(value, str) and value.strip() else None


def _creator(info, channel):
    """The show/channel author (host names often live here): creators list,
    creator, artist, album_artist, then uploader if it isn't the channel."""
    creators = info.get("creators")
    if isinstance(creators, list):
        joined = " ".join(c for c in (_clean_str(x) for x in creators) if c)
        if joined:
            return joined
    for key in ("creator", "artist", "album_artist"):
        value = _clean_str(info.get(key))
        if value:
            return value
    uploader = _clean_str(info.get("uploader"))
    if uploader and uploader != channel:
        return uploader
    return None


def ytdlp_context(info) -> dict:
    """yt-dlp info dict -> {title, channel, creator, description, chapters, tags},
    omitting anything missing or empty. Channel falls back through uploader,
    then series/album (podcast extractors)."""
    if not isinstance(info, dict):
        return {}
    ctx = {}
    title = _clean_str(info.get("title"))
    if title:
        ctx["title"] = title
    for key in ("channel", "uploader", "series", "album"):
        channel = _clean_str(info.get(key))
        if channel:
            ctx["channel"] = channel
            break
    creator = _creator(info, ctx.get("channel"))
    if creator:
        ctx["creator"] = creator[:CONTEXT_CREATOR_MAX].strip()
    desc = _clean_str(info.get("description"))
    if desc:
        ctx["description"] = desc[:CONTEXT_DESCRIPTION_MAX]
    chapters = info.get("chapters")
    if isinstance(chapters, list):
        titles = [t for t in (_clean_str(c.get("title")) for c in chapters
                              if isinstance(c, dict)) if t]
        if titles:
            ctx["chapters"] = titles[:CONTEXT_CHAPTERS_MAX]
    tags = info.get("tags")
    if isinstance(tags, list):
        clean = [t for t in (_clean_str(x) for x in tags) if t]
        if clean:
            ctx["tags"] = clean[:CONTEXT_TAGS_MAX]
    return ctx


def apple_context(r0) -> dict:
    """iTunes episode lookup result -> the same shape as ytdlp_context."""
    if not isinstance(r0, dict):
        return {}
    return ytdlp_context({"title": r0.get("trackName"),
                          "channel": r0.get("collectionName"),
                          "creator": r0.get("artistName"),
                          "description": r0.get("description")})


def write_context(d: Path, ctx: dict) -> None:
    (d / "context.json").write_text(json.dumps(ctx), encoding="utf-8")


def _read_context_file(d: Path):
    """The parsed context.json dict, or None if absent/unreadable/not a dict."""
    try:
        data = _read_json(d / "context.json")
    except OSError:
        return None
    return data if isinstance(data, dict) else None


def context_path_for(d: Path):
    """Path to usable context (not the 'unavailable' marker), else None."""
    data = _read_context_file(d)
    if not data or data.get("unavailable"):
        return None
    return str(d / "context.json")


def fetch_context(source: str) -> dict:
    """Metadata only, no audio, for a cache entry made before v0.9.0.
    Apple links go to the iTunes lookup first (yt-dlp's Apple extractor is
    the flaky one); everything else is a yt-dlp probe. May raise."""
    if _apple_ids(source) is not None:
        # Lookup only: the details live in the lookup result, and resolving a
        # playable URL would add an RSS fetch and fail on subscriber-only
        # episodes that still have a perfectly good show name and notes.
        try:
            ctx = apple_context(_apple_episode(source))
            if ctx:
                return ctx
        except Exception:  # any lookup failure: fall through to yt-dlp
            pass
    ytdlp = ytdlp_command()
    if not ytdlp:
        return {}
    probe = subprocess.run(
        [*ytdlp, "--no-warnings", "--dump-json", "--no-download", "--no-playlist", source],
        capture_output=True, text=True, timeout=CONTEXT_FETCH_TIMEOUT,
    )
    if probe.returncode != 0:
        return {}
    return ytdlp_context(json.loads(probe.stdout))


def _backfill_context(d: Path, source: str) -> None:
    """Best-effort, once per entry: a cache hit must never fail or change its
    answer because metadata could not be fetched. A failure is recorded so the
    hits within CONTEXT_RETRY_DAYS don't each wait on the network again."""
    if not is_url(source):
        return
    existing = _read_context_file(d)
    if existing and not existing.get("unavailable"):
        return
    if existing:
        try:
            checked = datetime.fromisoformat(existing.get("checked_date", ""))
            # A date in the future (clock skew, hand edit) is not trusted to
            # postpone the retry; it counts as expired like an unreadable one.
            if timedelta(0) <= datetime.now(timezone.utc) - checked < timedelta(days=CONTEXT_RETRY_DAYS):
                return
        except (TypeError, ValueError):
            pass  # unreadable date: treat the marker as expired
    try:
        ctx = fetch_context(source)
    except Exception:  # timeout, bad JSON, network: all mean "not this time"
        ctx = None
    try:
        if ctx:
            write_context(d, ctx)
            return
        (d / "context.json").write_text(json.dumps(
            {"unavailable": True, "checked_date": datetime.now(timezone.utc).isoformat()}), encoding="utf-8")
        when = f"after {CONTEXT_RETRY_DAYS} days"
    except OSError:
        when = "on the next run"
    print(f"note: could not fetch source details for name correction; will retry {when}",
          file=sys.stderr)


# ── Cache management ────────────────────────────────────────────────
# Retention is opt-in: no config -> nothing is ever auto-deleted.
def config_path() -> Path:
    return cache_dir() / "config.json"


def load_config() -> dict:
    cfg = _read_json(config_path())
    return cfg if isinstance(cfg, dict) else {}


def save_config(cfg: dict):
    cache_dir().mkdir(parents=True, exist_ok=True)
    _atomic_write_text(config_path(), json.dumps(cfg))


def _iter_entries():
    d = cache_dir()
    if not d.exists():
        return
    for sub in sorted(d.iterdir()):
        if sub.is_dir() and (sub / "meta.json").exists():
            yield sub


TEMP_MAX_AGE = 3600


def _clean_stale_temps() -> None:
    """Leftovers of an interrupted _atomic_write_text. Done here, not in
    _iter_entries(), so read-only commands like --cache-info never delete."""
    cutoff = time.time() - TEMP_MAX_AGE
    for sub in _iter_entries():
        for tmp in sub.glob(".meta.json.tmp-*"):
            try:
                if tmp.stat().st_mtime < cutoff:
                    tmp.unlink()
            except OSError:
                pass


def prune_expired() -> int:
    """Delete entries older than the configured retention. No config -> no-op
    (apart from clearing stale temp files)."""
    _clean_stale_temps()
    days = load_config().get("retention_days")
    if not days:
        return 0
    cutoff = time.time() - days * 86400
    n = 0
    for sub in list(_iter_entries()):
        meta = _read_json(sub / "meta.json")
        if entry_cached_ts(sub, meta if isinstance(meta, dict) else {}) < cutoff:
            shutil.rmtree(sub, ignore_errors=True)
            n += 1
    return n


def cmd_cache_info() -> int:
    entries, total = [], 0
    for sub in _iter_entries():
        meta = _read_json(sub / "meta.json")
        if not isinstance(meta, dict):
            meta = {}
        size = sum(f.stat().st_size for f in sub.rglob("*") if f.is_file())
        total += size
        entries.append({
            "key": sub.name[:12],
            "title": meta.get("title", ""),
            "source": meta.get("source", ""),
            "cached_date": datetime.fromtimestamp(
                entry_cached_ts(sub, meta)).strftime("%Y-%m-%d %H:%M"),
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
            if (_read_json(sub / "meta.json") or {}).get("source") == source:
                target = sub
                break
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
        cfg["retention_notice_shown"] = True
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
    cfg["retention_notice_shown"] = True
    save_config(cfg)
    print(f"retention set: cache entries older than {days} days are pruned on next run")
    return 0


def retention_notice():
    """The one-time notice, or None once acknowledged."""
    cfg = load_config()
    if cfg.get("retention_notice_shown"):
        return None
    return {"cache_dir": str(cache_dir()), "retention_days": cfg.get("retention_days")}


def cmd_ack_retention_notice() -> int:
    p = config_path()
    if p.exists() and not isinstance(_read_json(p), dict):
        print(f"config {p} is unreadable; not overwriting it — fix or delete it "
              "(the retention notice keeps appearing until then)", file=sys.stderr)
        return 2
    cfg = load_config()
    cfg["retention_notice_shown"] = True
    save_config(cfg)
    print("retention notice acknowledged")
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
#
# The conversion is gated per segment (v0.7.2). Simplified-to-Traditional converters
# assume their input IS Simplified. 干 / 里 / 吃 are perfectly valid Traditional
# characters that also happen to be the Simplified form of 乾 / 裏 / 喫, so an
# unconditional pass rewrites transcripts that were already Traditional. Measured on
# 22 real transcripts (337k chars, all already Traditional): a second s2twp pass
# changed 625 places, 175 of them 文件 -> 檔案. In that corpus 文件 always meant
# "document" (ISO audits, design specs), never "computer file" — the phrase table is
# right for Simplified input and wrong here.
#
# Gate: a character is evidence of Simplified input only if the converter changes it
# AND it is not in _ZH_AMBIGUOUS. Segments with no evidence are left untouched.
# Splitting per segment matters because the drift this guard exists for is partial:
# the tail of a long transcript goes Simplified while the head stayed Traditional.
_ZH_PROMPT = "以下是用繁體中文記錄的對話內容。"
_OPENCC = None  # lazy: None=untried, False=unavailable/disabled

# Valid Traditional characters that are ALSO the Simplified form of some other
# Traditional character. Derived from OpenCC's STCharacters.txt: entries whose
# Traditional candidate list contains the character itself. Embedded rather than read
# from the installed package because only opencc-python-reimplemented ships plain-text
# dictionaries; the official binding ships binary .ocd2. Regenerate with:
#   grep -P '^(.)\t.*\1' <opencc>/dictionary/STCharacters.txt | cut -f1 | tr -d '\n'
_ZH_AMBIGUOUS = frozenset(
    "㐹万丑丰了于云亘仆仇价仿伙余佛佣俊修借僵克党冬准凌几凶出划刮制千升卜占卷厂厘"
    "只台叶吁吃合吊同后向周咨咸咽哄唇喂噪回困夫夸奸姜娘它家尸局岩岳巨布帘席干幸广"
    "庵弦彩征御志念恤愈愿戚才扎托扣折抵拐挂挨挽据搜斗旋昆暗曲朱朴杆杠杯杰松板极柜"
    "栗核梁欲沈沾泛注涂涌淀游漓熏玩璇症皂矩确私秋种筑系胄背胜胡腊腌膻致舍芸苔苹范"
    "荐蒙蔑虫蚝蜡蝎表谷跖辟适郁酸采里雕面"
)

# Newlines and CJK/ASCII punctuation. OpenCC phrase conversion never spans punctuation,
# so splitting here costs nothing and keeps a drifted sentence from dragging its
# neighbours through the converter.
_ZH_SEGMENT_RE = re.compile(r"([\n。！？；，、：｜!?;,:|]+)")


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


def _zh_has_simplified(text, conv):
    """True if `text` holds a character that is evidence of Simplified input.

    Only depends on conv.convert(), so any object with that method works (tests
    pass a stub). Ambiguous characters are skipped: they are valid Traditional on
    their own and say nothing about the rest of the segment.
    """
    for ch in set(text):
        if ch in _ZH_AMBIGUOUS:
            continue
        try:
            if conv.convert(ch) != ch:
                return True
        except Exception:
            return False
    return False


def _maybe_to_traditional(text, language):
    conv = _get_zh_converter() if (language or "").lower().startswith("zh") else None
    if not conv or not text:
        return text
    try:
        parts = _ZH_SEGMENT_RE.split(text)  # even index = content, odd = separator
        return "".join(
            conv.convert(part)
            if i % 2 == 0 and _zh_has_simplified(part, conv) else part
            for i, part in enumerate(parts)
        )
    except Exception:
        return text


# ── Subtitle export (SRT/VTT, v0.6.0) ───────────────────────────────
# Segment-level timestamps come from the backend (see _run_backend); formatting
# to SRT/VTT text is backend-agnostic and lives here so it is testable in
# isolation. Deliberately NOT run through _collapse_repetitions: that regex
# collapses repeated phrases across the flat transcript, which has no clean
# mapping back onto discrete, already-timestamped segments. Segment text does
# still get the same OpenCC pass as the plain-text transcript (see main()).

def _split_timestamp(seconds):
    """seconds -> (hours, minutes, secs, ms), rounded half-up to the millisecond.
    Uses Decimal on the string form of `seconds` instead of float math: binary
    floats can't represent most decimals exactly, so e.g. round(1234.5) can
    land either side of .5 depending on representation error. Decimal(str(x))
    recovers the value's shortest decimal repr (what Python's own float repr
    already computes) and rounds it deterministically."""
    if seconds < 0:
        seconds = 0
    total_ms = int((Decimal(str(seconds)) * 1000).to_integral_value(rounding=ROUND_HALF_UP))
    hours, rem = divmod(total_ms, 3_600_000)
    minutes, rem = divmod(rem, 60_000)
    secs, ms = divmod(rem, 1000)
    return hours, minutes, secs, ms


def _format_timestamp(seconds, sep=","):
    """sep="," -> SRT (HH:MM:SS,mmm); sep="." -> WebVTT (HH:MM:SS.mmm)."""
    h, m, s, ms = _split_timestamp(seconds)
    return f"{h:02d}:{m:02d}:{s:02d}{sep}{ms:03d}"


def _subtitle_blocks(segments):
    """Shared iteration: drop segments whose text is blank after stripping —
    an empty-text cue is not meaningful to a subtitle reader."""
    for seg in segments:
        text = (seg.get("text") or "").strip()
        if text:
            yield seg["start"], seg["end"], text


def format_srt(segments) -> str:
    blocks = [f"{i}\n{_format_timestamp(start, ',')} --> {_format_timestamp(end, ',')}\n{text}"
              for i, (start, end, text) in enumerate(_subtitle_blocks(segments), start=1)]
    return "\n\n".join(blocks) + ("\n" if blocks else "")


def format_vtt(segments) -> str:
    blocks = ["WEBVTT"] + [
        f"{_format_timestamp(start, '.')} --> {_format_timestamp(end, '.')}\n{text}"
        for start, end, text in _subtitle_blocks(segments)]
    return "\n\n".join(blocks) + "\n"


DEFAULT_MODEL = "large-v3-turbo"

# Community fine-tune aliases: one bare name fans out to the right per-backend
# conversion repo (the upstream releases are HF-transformers-format only, which
# none of our backends load directly). None = no known conversion for that
# backend. whisper-cpp is absent on purpose — it never consults resolve_model
# (its model is the AUDIO_TLDR_WHISPER_CPP_MODEL GGML file; community GGML
# conversions of these models exist on Hugging Face).
MODEL_ALIASES = {
    "breeze-asr-25": {
        "mlx-whisper": "eoleedi/Breeze-ASR-25-mlx",
        "faster-whisper": "SoybeanMilk/faster-whisper-Breeze-ASR-25",
        "openai-whisper": None,
    },
}


class ModelAliasError(Exception):
    """A model alias was requested on a backend with no known conversion."""


def resolve_model(backend: str, cli_model):
    """Pick the whisper model: --model > AUDIO_TLDR_MODEL env > large-v3-turbo.
    Accepts canonical names (large-v3-turbo), whisper-prefixed names
    (whisper-large-v3-turbo), a known alias from MODEL_ALIASES
    (case-insensitive, e.g. breeze-asr-25), or a full HF repo path (kept
    as-is). mlx needs a repo path, so bare names get the mlx-community/whisper-
    prefix; the other backends take canonical names directly. whisper-cpp
    ignores this entirely (its model is the AUDIO_TLDR_WHISPER_CPP_MODEL file).
    Raises ModelAliasError when an alias has no conversion for `backend`."""
    name = cli_model or os.environ.get("AUDIO_TLDR_MODEL") or DEFAULT_MODEL
    alias = MODEL_ALIASES.get(name.lower())
    if alias is not None:
        repo = alias.get(backend)
        if repo is None:
            supported = ", ".join(k for k, v in alias.items() if v)
            raise ModelAliasError(
                f"model '{name}' has no known {backend} conversion; "
                f"it is available on: {supported}. Install one of those backends, "
                f"or pass a full HF repo path you trust instead")
        return repo
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


# ── Segment extraction for CLI backends (v0.6.0) ────────────────────
# mlx-whisper and faster-whisper are Python APIs that already return segments
# in-process. whisper-cpp and openai-whisper are invoked as subprocesses, so
# their segments come from an extra machine-readable output file requested
# only when a caller actually wants timestamps (--output-json / --output_format
# json cost real CLI work, so the plain --format txt path never asks for them).

def _parse_whisper_cpp_json(json_path: Path):
    """whisper-cli --output-json writes {"transcription": [{"offsets":
    {"from": ms, "to": ms}, "text": ...}, ...]}. Returns None on any I/O or
    shape problem — callers treat that the same as "backend gave nothing"."""
    try:
        data = json.loads(_read_text(json_path))
    except (OSError, ValueError):
        return None
    out = []
    for seg in data.get("transcription", []):
        text = (seg.get("text") or "").strip()
        if not text:
            continue
        offsets = seg.get("offsets") or {}
        out.append({"start": offsets.get("from", 0) / 1000.0,
                    "end": offsets.get("to", 0) / 1000.0, "text": text})
    return out or None


def _parse_openai_whisper_json(json_path: Path):
    """openai-whisper --output_format json writes {"text": ..., "segments":
    [{"start": sec, "end": sec, "text": ...}, ...], "language": ...}."""
    try:
        data = json.loads(_read_text(json_path))
    except (OSError, ValueError):
        return None
    out = []
    for seg in data.get("segments", []):
        text = (seg.get("text") or "").strip()
        if not text:
            continue
        out.append({"start": seg.get("start", 0.0), "end": seg.get("end", 0.0), "text": text})
    return out or None


def _run_backend(backend, audio_path, language, model_name=None, want_segments=False):
    """Returns (text, duration, language, segments). `segments` is a list of
    {start, end, text} dicts when the backend produced them (only attempted
    when want_segments is True), or None otherwise — None means "this backend
    could not supply timestamps for this run", never a fabricated guess."""
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
        segments = None
        if want_segments and r.get("segments"):
            segments = [{"start": s["start"], "end": s["end"], "text": s["text"].strip()}
                        for s in r["segments"]]
        return r["text"].strip(), dur, r.get("language", language or ""), segments
    if backend == "faster-whisper":
        from faster_whisper import WhisperModel
        model = WhisperModel(model_id)
        raw_segments, info = model.transcribe(audio_path, language=language,
                                              initial_prompt=zh_prompt)
        segs = list(raw_segments)
        text = " ".join(s.text.strip() for s in segs)
        dur = segs[-1].end if segs else 0.0
        segments = None
        if want_segments and segs:
            segments = [{"start": s.start, "end": s.end, "text": s.text.strip()} for s in segs]
        return text, dur, info.language, segments
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
            if want_segments:
                cmd += ["--output-json"]
            subprocess.run(cmd, capture_output=True, check=True, timeout=7200)
            text = _read_text(Path(wav + ".txt")).strip()
            segments = _parse_whisper_cpp_json(Path(wav + ".json")) if want_segments else None
            return text, 0.0, language or "", segments
        finally:
            shutil.rmtree(workdir, ignore_errors=True)
    if backend == "openai-whisper":
        outdir = tempfile.mkdtemp(prefix="audio-tldr-")
        try:
            # "all" also writes vtt/srt/tsv we don't use, but it's the only way to
            # get json (for segments) without changing what the txt file contains.
            out_fmt = "all" if want_segments else "txt"
            cmd = ["whisper", audio_path, "--model", model_id,
                   "--output_format", out_fmt, "--output_dir", outdir]
            if language:
                cmd += ["--language", language]
            if zh_prompt:
                cmd += ["--initial_prompt", zh_prompt]
            subprocess.run(cmd, capture_output=True, check=True, timeout=7200)
            txts = sorted(Path(outdir).glob("*.txt"))
            text = _read_text(txts[0]).strip()
            segments = None
            if want_segments:
                jsons = sorted(Path(outdir).glob("*.json"))
                segments = _parse_openai_whisper_json(jsons[0]) if jsons else None
            return text, 0.0, language or "", segments
        finally:
            shutil.rmtree(outdir, ignore_errors=True)
    raise ValueError(f"unknown backend {backend}")


def transcribe_audio(audio_path, backend, language=None, model=None,
                     want_segments=False, **options):
    """Transcription plus the post-processing main() caches, as one call, so
    scripts/asr_eval.py measures exactly what users get. `options` is where
    backend tuning (VAD, prompt carry-over, hotwords) arrives in v1.0 ③."""
    if options:
        raise TypeError(f"unsupported transcription options: {sorted(options)}")
    t0 = time.monotonic()
    # mlx-whisper / faster-whisper hand over segments for free, and the cached
    # transcript is written one segment per line; whisper-cpp / openai-whisper
    # already emit one line per segment in their .txt.
    ask = want_segments or backend in ("mlx-whisper", "faster-whisper")
    raw_text, duration, lang, segments = _run_backend(
        backend, audio_path, language, model, want_segments=ask)
    backend_seconds = round(time.monotonic() - t0, 2)
    t1 = time.monotonic()
    collapsed = _collapse_repetitions(raw_text)
    text = _maybe_to_traditional(collapsed, lang)
    text = wrap_lines(text, segments, lambda s: _maybe_to_traditional(s, lang))
    display = ([{**s, "text": _maybe_to_traditional(s["text"], lang)} for s in segments]
               if segments else None)
    if not want_segments:  # callers only get segments they asked for
        segments = display = None
    return {
        "raw_text": raw_text, "text": text,
        "collapsed_chars": len(raw_text) - len(collapsed),
        "segments": segments, "display_segments": display,
        "duration": duration, "language": lang,
        "backend_seconds": backend_seconds,
        "postprocess_seconds": round(time.monotonic() - t1, 2),
    }


def _ensure_subtitle(d: Path, meta: dict, fmt: str):
    """On a cache hit for --format srt/vtt: reuse the requested subtitle file if
    it's already on disk; else rebuild it from the cache entry's segments.json
    (cheap — no re-transcription) if that exists; else there is nothing to
    build it from (a pre-v0.6.0 entry, or one last transcribed as --format txt)
    and the caller must be told to re-transcribe. Returns (path_str, error);
    exactly one of the two is None."""
    sub_path = d / f"transcript.{fmt}"
    if sub_path.exists():
        return str(sub_path), None
    seg_path = resolve_entry_file(d, "segments")
    if seg_path is None:
        return None, (
            f"cached transcript has no segment timestamps for --format {fmt} "
            "(cached before subtitle export was added, or last transcribed with "
            f"--format txt) — re-run with --force --format {fmt} to regenerate with timestamps")
    try:
        segments = _read_json(seg_path)
        if not isinstance(segments, list):
            raise ValueError("segments.json is not a list")
    except (OSError, ValueError):
        return None, (
            f"cached segments.json is unreadable — re-run with --force --format {fmt} "
            "to regenerate with timestamps")
    lang = meta.get("language")
    segments = [{**s, "text": _maybe_to_traditional(s["text"], lang)} for s in segments]
    content = format_srt(segments) if fmt == "srt" else format_vtt(segments)
    sub_path.write_text(content, encoding="utf-8")
    return str(sub_path), None


def main(argv=None):
    raw_argv = list(argv) if argv is not None else sys.argv[1:]
    _honor_explicit_python(raw_argv)
    ap = argparse.ArgumentParser(description="audio-tldr transcription engine")
    ap.add_argument("source", nargs="?", help="URL or local audio/video file path")
    ap.add_argument("--language", default=None)
    ap.add_argument("--model", default=None,
                    help="whisper model (default: large-v3-turbo; also via AUDIO_TLDR_MODEL). "
                         "Bare names map per backend (mlx gets the mlx-community/ prefix); "
                         "a full HF repo path is used as-is; named aliases map to the "
                         "backend's community conversion (breeze-asr-25 — Taiwanese "
                         "Mandarin fine-tune). Ignored by whisper-cpp")
    ap.add_argument("--force", action="store_true", help="ignore cache, re-transcribe")
    ap.add_argument("--cache-info", action="store_true", help="list cached transcripts (JSON)")
    ap.add_argument("--clear", metavar="SOURCE", help="delete the cache entry for one source")
    ap.add_argument("--clear-all", action="store_true", help="delete ALL cache entries (needs --yes)")
    ap.add_argument("--yes", action="store_true", help="confirm --clear-all")
    ap.add_argument("--set-retention", metavar="DAYS",
                    help="auto-prune entries older than DAYS on each run; 'off' = keep forever (default)")
    ap.add_argument("--ack-retention-notice", action="store_true",
                    help="record that the user was told where transcripts are kept "
                         "(stops the retention_notice field)")
    ap.add_argument("--keep-audio", action="store_true",
                    help="keep the downloaded audio in the cache entry instead of deleting it (URL sources)")
    ap.add_argument("--doctor", action="store_true",
                    help="diagnose the environment (python, backends, tools, other interpreters, Metal) as JSON")
    ap.add_argument("--format", choices=["txt", "srt", "vtt"], default="txt",
                    help="output format (default: txt, unchanged behavior). srt/vtt additionally "
                         "write a subtitle file with segment timestamps alongside transcript.txt; "
                         "errors clearly if the backend or cache entry has no timestamps")
    args = ap.parse_args(raw_argv)
    want_segments = args.format in ("srt", "vtt")

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
    if args.ack_retention_notice:
        return cmd_ack_retention_notice()

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
    d = cache_dir() / key
    if not args.force:
        meta = load_cached(key)
        if meta:
            _backfill_context(d, args.source)
            if want_segments:
                sub_path, err = _ensure_subtitle(d, meta, args.format)
                if err:
                    print(err, file=sys.stderr)
                    return 2
                meta = {**meta, f"{args.format}_path": sub_path}
            if args.keep_audio and not resolve_entry_file(d, "audio"):
                print("note: --keep-audio ignored on cache hit (transcript already cached; "
                      "re-run with --force to download and keep the audio)", file=sys.stderr)
            out = {**public_meta(d, meta), "cache_hit": True}
            cp = context_path_for(d)
            if cp:
                out["context_path"] = cp
            notice = retention_notice()
            if notice:
                out["retention_notice"] = notice
            print(json.dumps(out, ensure_ascii=False))
            return 0

    backend = detect_backend()
    if backend is None:
        _maybe_reexec(raw_argv)  # switches interpreter (never returns) if one has a backend
        print(INSTALL_GUIDE, file=sys.stderr)
        print("tip: run --doctor to see which interpreters/tools were probed",
              file=sys.stderr)
        return 3

    # Validate the model choice now, before spending minutes on a download that
    # a bad alias/backend combination would only throw away.
    if backend != "whisper-cpp":
        try:
            resolve_model(backend, args.model)
        except ModelAliasError as e:
            print(str(e), file=sys.stderr)
            return 2

    title = Path(args.source).stem
    audio_path = args.source
    tmpdir = None
    kept_audio = None
    media_url = None
    context = None
    dl_t0 = time.monotonic()
    try:
        if is_url(args.source):
            tmpdir = tempfile.mkdtemp(prefix="audio-tldr-dl-")
            try:
                audio_path, title, info = download_audio(args.source, Path(tmpdir))
                context = ytdlp_context(info)
            except DownloadError:
                resolved = resolve_apple_podcast(args.source)
                if resolved is None:
                    raise
                # The fallback's own yt-dlp info describes a bare media file;
                # the lookup result is what knows the show and the episode.
                media_url, ep_title, context = resolved
                print("note: Apple Podcasts extractor failed; falling back to the "
                      "episode's public media URL (cache identity stays on the Apple link)",
                      file=sys.stderr)
                audio_path, dl_title, _ = download_audio(media_url, Path(tmpdir))
                title = ep_title or dl_title
        # Download wall-clock (URL sources only; includes the Apple-fallback retry).
        download_seconds = round(time.monotonic() - dl_t0, 2) if tmpdir else None
        res = transcribe_audio(audio_path, backend, args.language, args.model,
                               want_segments=want_segments)
        text, duration, lang, segments = (
            res["raw_text"], res["duration"], res["language"], res["segments"])
        # Wall-clock of the transcription call only (download/NAS-style side steps
        # excluded), so duration / processing_seconds gives the backend's realtime factor.
        processing_seconds = res["backend_seconds"]
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

    if res["collapsed_chars"]:
        print(f"note: collapsed repeated phrases ({res['collapsed_chars']} chars removed — "
              f"likely whisper tail hallucination; AUDIO_TLDR_DEREPEAT=off to disable)",
              file=sys.stderr)
    text = res["text"]
    postprocess_seconds = res["postprocess_seconds"]
    w_t0 = time.monotonic()
    d.mkdir(parents=True, exist_ok=True)
    t_path = d / "transcript.txt"
    remove_correction_files(d)
    t_path.write_text(text, encoding="utf-8")
    if context:
        # Only a fresh fetch replaces it: a --force re-run that found nothing
        # keeps the details an earlier run did find. Like --keep-audio, an
        # optional side-effect must never discard the transcription.
        try:
            write_context(d, context)
        except OSError as e:
            print(f"warning: could not save source details ({e}); continuing without them",
                  file=sys.stderr)
    write_acc = time.monotonic() - w_t0
    model_used = (os.environ.get("AUDIO_TLDR_WHISPER_CPP_MODEL", "")
                  if backend == "whisper-cpp" else resolve_model(backend, args.model))
    meta = {"transcript_path": str(t_path), "title": title, "duration": duration,
            "processing_seconds": processing_seconds,
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

    sub_error = None
    if want_segments:
        if segments:
            # Cache the raw (pre-OpenCC) segments once — a later request for the
            # *other* subtitle format reformats from this instead of re-transcribing.
            w_t1 = time.monotonic()
            seg_path = d / "segments.json"
            seg_path.write_text(json.dumps(segments))
            zh_segments = res["display_segments"]
            content = format_srt(zh_segments) if args.format == "srt" else format_vtt(zh_segments)
            sub_path = d / f"transcript.{args.format}"
            sub_path.write_text(content, encoding="utf-8")
            write_acc += time.monotonic() - w_t1
            meta["segments_path"] = str(seg_path)
            meta[f"{args.format}_path"] = str(sub_path)
        else:
            sub_error = (
                f"backend {backend} does not provide segment-level timestamps needed for "
                f"--format {args.format}; the transcript was still cached as text "
                "(switch to a backend with segment support, e.g. mlx-whisper or "
                "faster-whisper, and re-run with --force)")

    # Stage breakdown (seconds). backend_call == processing_seconds (kept for
    # backward compatibility); write covers cache-file writes incl. subtitle
    # formatting; unmeasurable stages are null (e.g. download for local files).
    meta["timings"] = {
        "download": download_seconds,
        "backend_call": processing_seconds,
        "postprocess": postprocess_seconds,
        "write": round(write_acc, 2),
    }
    meta["schema_version"] = SCHEMA_VERSION
    meta["cached_date"] = datetime.now(timezone.utc).isoformat()
    meta["files"] = {n: f for n, f in ENTRY_FILES.items() if resolve_entry_file(d, n)}
    _atomic_write_text(d / "meta.json", json.dumps(meta))
    if sub_error:
        print(sub_error, file=sys.stderr)
        return 2
    out = {**public_meta(d, meta), "cache_hit": False}
    cp = context_path_for(d)
    if cp:
        out["context_path"] = cp
    notice = retention_notice()
    if notice:
        out["retention_notice"] = notice
    print(json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    utf8_stdio()
    sys.exit(main())
