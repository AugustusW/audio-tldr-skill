# audio-tldr

> **Any video, audio, or podcast → key takeaways. Transcribed locally, cached forever.**

English | [繁體中文](./README.zh-TW.md)

[![License](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.9%2B-blue.svg)](https://www.python.org/)
[![Platform](https://img.shields.io/badge/platform-macOS%20%7C%20Linux%20%7C%20Windows-lightgrey.svg)](#prerequisites)
[![Claude Code](https://img.shields.io/badge/Claude%20Code-skill%20%2B%20plugin-orange.svg)](https://claude.com/claude-code)
[![Codex](https://img.shields.io/badge/Codex-compatible-black.svg)](https://developers.openai.com/codex/skills)

An agent skill — open [SKILL.md standard](https://developers.openai.com/codex/skills), works in
[Claude Code](https://claude.com/claude-code) **and** [Codex](https://developers.openai.com/codex/skills) —
that turns long-form media into **3–7 key
takeaways + a summary**. Transcription runs locally with whisper and is cached by content hash —
while a cache entry exists, the same source is **not transcribed again** (unless you `--force`).
Ask for a different angle later and it re-digests from cache in seconds.

> First-run transcription time depends on your hardware, model, and backend — after that, the cache answers.

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
re-upload, re-transcribe, re-pay      transcribe once, reuse from cache
```

## Features

- ✓ YouTube, podcasts, and any yt-dlp-supported URL — or local audio/video files
- ✓ Local media pipeline: download, transcription, cache all run on your machine — audio is never uploaded (see [Privacy](#privacy))
- ✓ Content-hash cache: re-summarizing (any angle) reuses the transcript while the entry exists
- ✓ Whisper backend auto-detection: mlx-whisper / faster-whisper / whisper.cpp / openai-whisper
- ✓ Language auto-detection; optional Simplified→Traditional Chinese conversion (OpenCC)
- ✓ Cache management built in: list, clear one, clear all, opt-in retention
- ✓ Timeline for long content (> 20 min)
- ✓ Digests saved to an output folder as Markdown or HTML — transcripts stay in the cache
- ✓ Conversational digest prompt: no request stated? The agent asks in plain text (key takeaways / meeting minutes / detailed summary / action items / Q&A / translation / your own words)
- ✓ Translation at the digest layer: digests in any language, or a faithful full-transcript translation
- ✓ Optional preferences file for standing habits — zero setup required
- ✓ Interpreter auto-selection: backend installed in another Python (e.g. Homebrew) is found and used automatically; `--doctor` diagnoses the environment
- ✓ Apple Podcasts fallback built in: when yt-dlp's extractor fails, episodes resolve via the iTunes lookup API — cache identity stays on your original link; a show link (no episode id) automatically uses the latest episode
- ✓ Install by copy, as a Claude Code plugin, **or** into Codex (open SKILL.md standard)

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

**Option C — Codex CLI / ChatGPT app:**

The skill follows the open SKILL.md standard, so it works in Codex as-is. Copy the skill
folder into Codex's skills directory:

```bash
git clone https://github.com/AugustusW/audio-tldr-skill.git
cp -r audio-tldr-skill/skills/audio-tldr ~/.codex/skills/audio-tldr        # personal
# or, per-project: cp -r audio-tldr-skill/skills/audio-tldr <repo>/.codex/skills/audio-tldr
```

Invoke it with a `$audio-tldr` mention, or let Codex pick it implicitly when you ask to
summarize audio/video. The transcript cache (`~/.cache/audio-tldr/`) and the preferences file
(`~/.config/audio-tldr/preferences.md`) are shared with Claude Code — transcribe once, digest
anywhere.

## Prerequisites

The media pipeline — download, transcription, cache — runs entirely on your machine.

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

For URL sources, make sure you have the right to download and process the content, and comply
with the source site's terms and your local copyright law.

### Choosing a model

The defaults favor safety over quality on CPU (`small` everywhere except mlx). Override with
`AUDIO_TLDR_MODEL` — the name must be valid for your active backend:

| Situation | Suggested model |
|---|---|
| CPU / quick tests | `small` |
| General Chinese summaries | `medium` |
| Names, jargon, accuracy-critical | `large-v3` |
| Capable GPU, speed + quality | `large-v3` or `large-v3-turbo` |

```powershell
$env:AUDIO_TLDR_MODEL = "large-v3"    # PowerShell; bash/zsh: export AUDIO_TLDR_MODEL=large-v3
```

**Optional — Traditional Chinese:** whisper often emits Simplified Chinese. `pip install opencc`
and Chinese transcripts are converted to Taiwan Traditional automatically (plus the model is
biased toward Traditional vocabulary). Not installed → transcripts are left as-is.

### Windows notes

Windows is supported by the underlying Python stack, but the full flow has **not yet been
verified on Windows** — reports welcome. Install with PowerShell:

```powershell
# prerequisites (winget shown; Chocolatey: choco install ffmpeg yt-dlp)
winget install Gyan.FFmpeg
winget install yt-dlp.yt-dlp
py -3 -m pip install faster-whisper      # recommended backend on Windows

# install the skill (manual copy)
git clone https://github.com/AugustusW/audio-tldr-skill.git
$skillsDir = "$env:USERPROFILE\.claude\skills"
New-Item -ItemType Directory -Force -Path $skillsDir | Out-Null
Copy-Item -Recurse -Force "audio-tldr-skill\skills\audio-tldr" $skillsDir
```

Manual copy does not auto-update, and `-Force` overwrites an existing `audio-tldr` folder —
prefer the plugin install if you want managed versions.

- **Python command** — if `python3` isn't recognized, use `python` or the py launcher (`py -3`);
  the skill tells Claude to fall back automatically, but substitute accordingly when running the
  script yourself.
- **Skill path** — Claude Code on Windows reads skills from `%USERPROFILE%\.claude\skills\`
  (plugin install works identically to macOS/Linux).
- **GPU (optional)** — faster-whisper runs on CPU out of the box. NVIDIA acceleration goes
  through CTranslate2; check that a CUDA device is visible with
  `py -3 -c "import ctranslate2; print(ctranslate2.get_cuda_device_count())"`.
  Non-zero means CTranslate2 can see the GPU — it does **not** guarantee the CUDA runtime,
  cuBLAS/cuDNN DLLs, and GPU model loading all work; run one short real transcription to
  confirm. Required CUDA/cuDNN versions: see the
  [faster-whisper README](https://github.com/SYSTRAN/faster-whisper#gpu).
- mlx-whisper is Apple-Silicon-only. whisper.cpp on Windows needs a `whisper-cli.exe` on PATH
  plus `AUDIO_TLDR_WHISPER_CPP_MODEL`.

## Usage

```
> summarize https://www.youtube.com/watch?v=xxxx
> give me the key points from this podcast: https://podcasts.apple.com/...
> /audio-tldr ~/Downloads/meeting-recording.m4a
> summarize this talk for a beginner — action items only: https://youtu.be/xxxx
> (later) same video, but focus only on what they said about pricing
```

State your needs in the request — focus, audience, format, length, language — and the digest
follows them instead of the default takeaways+summary structure. The last one re-uses the
cached transcript — instant, no re-transcription.

## How it works

Two phases, deliberately separated:

1. **Transcribe** (`scripts/transcribe.py`) — resolves a cache key (normalized URL or file
   content hash), returns instantly on a hit; otherwise downloads via yt-dlp, transcribes with
   the best available whisper backend, and caches `transcript.txt` + `meta.json` under
   `~/.cache/audio-tldr/<sha256>/`.
2. **Digest** — the agent reads the cached transcript and produces takeaways, a summary, and
   (for long content) an approximate timeline. If your request didn't say how to digest, it
   asks first — in plain conversational text, never a clickable menu, so it works over
   plain-text messaging channels too. Every digest is also saved to the output folder
   (default `./audio-tldr-output/`) as `<title>-<date>-<style>.md` (or `.html`).
   Re-digesting with a different focus skips phase 1 entirely.

## Privacy

Be precise about what stays local and what doesn't:

- **Your audio/video never leaves the machine.** No third-party transcription service is used,
  and the scripts in this repo contain no telemetry. Network access still happens where you'd
  expect: yt-dlp fetches URL sources from the source site, and whisper backends may download
  their model on first use (dependency behavior is governed by those projects).
- **The digest phase sends the transcript text (never the audio) to the model**, inside your own
  Claude session — exactly like asking Claude to read any local file.
- **Cached transcripts are unencrypted plaintext, kept indefinitely by default**, under
  `~/.cache/audio-tldr/`. After processing sensitive content, `--clear` that entry, or configure
  a retention period.
- **Digests persist in the output folder** (default `./audio-tldr-output/`, relative to your
  working directory) — including full-transcript translations, which carry essentially the whole
  transcript. The output folder has no clearing or retention mechanism; delete files manually,
  and add the folder to `.gitignore` if you run the skill inside a git-tracked directory.
- **Phase 1 only (sensitive recordings):** transcribe without ever handing the text to Claude —
  run the script yourself; stdout is metadata JSON only, and the transcript stays at the
  returned `transcript_path` until you delete it:

  ```bash
  # macOS/Linux
  python3 ~/.claude/skills/audio-tldr/scripts/transcribe.py "/path/to/recording.m4a"
  ```

  ```powershell
  # Windows PowerShell
  py -3 "$env:USERPROFILE\.claude\skills\audio-tldr\scripts\transcribe.py" "C:\path\to\recording.m4a"
  ```

## Preferences (optional)

Create `~/.config/audio-tldr/preferences.md` to set standing habits — every field is optional
and everything works without the file:

```markdown
output_dir: ~/Documents/audio-digests
timeline: off
auto_delete_audio: off
output_format: html
```

| field | default | meaning |
|---|---|---|
| `output_dir` | `./audio-tldr-output` | where digest files are saved |
| `timeline` | `on` | include a timeline section in digests when content warrants it |
| `auto_delete_audio` | `on` | delete downloaded audio after transcription; `off` keeps the mp3 in the cache entry |
| `output_format` | `md` | digest file format, `md` or `html`; a per-request choice always wins |

The file is read by the agent (Claude Code and Codex share it) — the install never asks you to
set it up, and defaults apply whenever it's absent.

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
| `--keep-audio` | keep the downloaded mp3 in the cache entry (default deletes it after transcription) |
| `--doctor` | JSON environment diagnosis: Python path/version, backend & tool visibility, other interpreters that have a backend, MLX Metal availability |

Environment variables:

| Variable | Purpose |
|---|---|
| `AUDIO_TLDR_MODEL` | override the whisper model for the active backend |
| `AUDIO_TLDR_WHISPER_CPP_MODEL` | path to a ggml model file (enables the whisper.cpp backend) |
| `AUDIO_TLDR_ZH_CONVERT` | Chinese conversion: `off`, or an OpenCC config (default `s2tw`) |
| `AUDIO_TLDR_PYTHON` | pin the Python interpreter the script runs under (wins over auto-probing). Useful when your whisper backend lives in a non-default Python (e.g. Homebrew 3.12) |

## Develop

```bash
git clone https://github.com/AugustusW/audio-tldr-skill.git
cd audio-tldr-skill
python3 -m pytest tests/   # 48 unit tests, no network or model needed
```

Versioning: every release bumps `version` in `.claude-plugin/plugin.json` **and**
`.claude-plugin/marketplace.json` (kept identical) and adds a [CHANGELOG](./CHANGELOG.md) entry.

## Status

v0.3.1 ([CHANGELOG](./CHANGELOG.md)) — core logic is covered by 48 offline unit tests (yt-dlp,
whisper backends, cache, and OpenCC are mocked; no network or models needed). The full flow has
been manually verified (2026-07-19: real YouTube download, transcription, cached re-digest,
Chinese conversion, `--keep-audio`, output-folder digests in md/html, transcript translation,
interpreter auto-selection from `/usr/bin/python3`, and the Apple Podcasts fallback end-to-end —
a real 53-min episode resolved via iTunes lookup, transcribed, and cache-hit on the original
Apple URL) on:

| Component | Verified version |
|---|---|
| macOS | 26.5.1 (Apple M4 Pro) |
| Python | 3.12.13 |
| mlx-whisper | 0.4.3 |
| ffmpeg | 8.1 |
| yt-dlp | 2026.06.09 |

Newer dependency versions may behave differently. Not yet covered by automated tests: real
downloads, the other three backends, and Windows. Codex support follows the open SKILL.md
standard; the transcription core was verified end-to-end inside Codex on 2026-07-19 (a real
53-min podcast downloaded, transcribed, and cache-hit, including the interpreter
auto-selection path). Digest-layer features (output folder, translation, preferences) have so
far been exercised in Claude Code only. Possible next: SRT export, speaker diarization.
Issues and PRs welcome.

## License

MIT. See [LICENSE](./LICENSE).

---

> Long content is worth hearing once — by your machine, not by you.
