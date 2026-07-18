# audio-tldr

> **Any video, audio, or podcast → key takeaways. Transcribed locally, cached forever.**

English | [繁體中文](./README.zh-TW.md)

[![License](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.9%2B-blue.svg)](https://www.python.org/)
[![Platform](https://img.shields.io/badge/platform-macOS%20%7C%20Linux%20%7C%20Windows-lightgrey.svg)](#prerequisites)
[![Claude Code](https://img.shields.io/badge/Claude%20Code-skill%20%2B%20plugin-orange.svg)](https://claude.com/claude-code)

A [Claude Code](https://claude.com/claude-code) skill that turns long-form media into **3–7 key
takeaways + a summary**. Transcription runs locally with whisper and is cached by content hash —
the same source is **never transcribed twice**. Ask for a different angle later and it re-digests
from cache in seconds.

> An hour of podcast is 10 minutes of transcription — but only once.

## Why?

Watching a 90-minute talk to extract 5 useful points is a bad trade. Sending audio to a cloud
API costs money and leaks content. And summarizing the same episode twice — because the first
summary had the wrong focus — means paying the transcription cost all over again.

```text
Without audio-tldr                    With audio-tldr
──────────────────                    ───────────────
watch the whole video                 paste the URL
take notes by hand                    get takeaways + summary
"summarize it differently…"           re-digest from cache, instant
re-upload, re-transcribe, re-pay      transcribe once, ever
```

## Features

- ✓ YouTube, podcasts, and any yt-dlp-supported URL — or local audio/video files
- ✓ Fully local: download, transcription, cache — nothing leaves your machine
- ✓ Content-hash cache: re-summarizing (any angle) never re-transcribes
- ✓ Whisper backend auto-detection: mlx-whisper / faster-whisper / whisper.cpp / openai-whisper
- ✓ Language auto-detection; optional Simplified→Traditional Chinese conversion (OpenCC)
- ✓ Cache management built in: list, clear one, clear all, opt-in retention
- ✓ Timeline for long content (> 20 min)
- ✓ Install by copy **or** as a Claude Code plugin

## Install

**Option A — copy the skill (simplest):**

```bash
git clone https://github.com/AugustusW/audio-tldr-skill.git
cp -r audio-tldr-skill/skills/audio-tldr ~/.claude/skills/
```

Invoke with `/audio-tldr`, or just ask Claude to summarize a video — it auto-triggers.

**Option B — install as a plugin:**

```
/plugin marketplace add AugustusW/audio-tldr-skill
/plugin install audio-tldr@audio-tldr-skill
```

Invoke with `/audio-tldr:audio-tldr`. Both options can coexist — plugin skills are namespaced.

## Prerequisites

Everything runs locally; nothing is uploaded anywhere.

| Requirement | Why | Install |
|---|---|---|
| Python 3.9+ | runs the transcription script | usually preinstalled |
| `yt-dlp` | download audio from URLs | `pip install yt-dlp` or `brew install yt-dlp` |
| `ffmpeg` | audio extraction/conversion | `brew install ffmpeg` / `apt install ffmpeg` |
| **One** whisper backend | speech-to-text | table below |

Whisper backends, in the order the skill auto-detects them:

| Backend | Best for | Install | Default model |
|---|---|---|---|
| [mlx-whisper](https://pypi.org/project/mlx-whisper/) | Apple Silicon (fastest) | `pip install mlx-whisper` | `large-v3-turbo` |
| [faster-whisper](https://pypi.org/project/faster-whisper/) | Cross-platform GPU/CPU | `pip install faster-whisper` | `small` |
| [whisper.cpp](https://github.com/ggerganov/whisper.cpp) | CPU, no Python deps | `brew install whisper-cpp` + set `AUDIO_TLDR_WHISPER_CPP_MODEL` | (your model file) |
| [openai-whisper](https://pypi.org/project/openai-whisper/) | Original CLI | `pip install openai-whisper` | `small` |

Local files don't need `yt-dlp` — only a whisper backend.

**Optional — Traditional Chinese:** whisper often emits Simplified Chinese. `pip install opencc`
and Chinese transcripts are converted to Taiwan Traditional automatically (plus the model is
biased toward Traditional vocabulary). Not installed → transcripts are left as-is.

## Usage

```
> summarize https://www.youtube.com/watch?v=xxxx
> give me the key points from this podcast: https://podcasts.apple.com/...
> /audio-tldr ~/Downloads/meeting-recording.m4a
> (later) same video, but focus only on what they said about pricing
```

The last one re-uses the cached transcript — instant, no re-transcription.

## How it works

Two phases, deliberately separated:

1. **Transcribe** (`scripts/transcribe.py`) — resolves a cache key (normalized URL or file
   content hash), returns instantly on a hit; otherwise downloads via yt-dlp, transcribes with
   the best available whisper backend, and caches `transcript.txt` + `meta.json` under
   `~/.cache/audio-tldr/<sha256>/`.
2. **Digest** — Claude reads the cached transcript and produces takeaways, a summary, and (for
   long content) an approximate timeline. Re-digesting with a different focus skips phase 1
   entirely.

## Cache & configuration

The cache is **kept forever by default** — nothing is auto-deleted unless you opt in.

Ask Claude, or run `scripts/transcribe.py` directly:

| Command | What it does |
|---|---|
| `--cache-info` | list cached transcripts + sizes (JSON) |
| `--clear "<source>"` | delete one entry |
| `--clear-all --yes` | delete everything |
| `--set-retention <days>` | auto-prune entries older than N days (`off` = keep forever) |
| `--force` | re-transcribe one source, ignoring cache |

Environment variables:

| Variable | Purpose |
|---|---|
| `AUDIO_TLDR_MODEL` | override the whisper model for the active backend |
| `AUDIO_TLDR_WHISPER_CPP_MODEL` | path to a ggml model file (enables the whisper.cpp backend) |
| `AUDIO_TLDR_ZH_CONVERT` | Chinese conversion: `off`, or an OpenCC config (default `s2tw`) |

## Develop

```bash
git clone https://github.com/AugustusW/audio-tldr-skill.git
cd audio-tldr-skill
python3 -m pytest tests/   # 18 unit tests, no network or model needed
```

## Status

v0.1.0 — core flow (transcribe → cache → digest), four whisper backends, Chinese conversion,
and cache management are working and tested end-to-end. Possible next: SRT export, speaker
diarization. Issues and PRs welcome.

## License

MIT. See [LICENSE](./LICENSE).

---

> Long content is worth hearing once — by your machine, not by you.
