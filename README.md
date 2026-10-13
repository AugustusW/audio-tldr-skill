# audio-tldr

> **Any video, audio, or podcast → key takeaways. Transcribed locally, cached forever.**

English | [繁體中文](./README.zh-TW.md)

[![Release](https://img.shields.io/github/v/release/AugustusW/audio-tldr-skill?color=brightgreen)](https://github.com/AugustusW/audio-tldr-skill/releases)
[![License](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/)
[![Platform](https://img.shields.io/badge/platform-macOS%20%7C%20Linux%20%7C%20Windows-lightgrey.svg)](#prerequisites)
[![Claude Code](https://img.shields.io/badge/Claude%20Code-skill%20%2B%20plugin-orange.svg)](https://claude.com/claude-code)
[![Codex](https://img.shields.io/badge/Codex-compatible-black.svg)](https://developers.openai.com/codex/skills)

![Demo: summarize a YouTube video from a cached transcript](./assets/demo.gif)

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
- ✓ Conversational digest prompt: no request stated? The agent asks in plain text, listing the template menu
- ✓ Digest templates: meeting minutes, key summary, analysis report — or save your own reusable format
- ✓ Opt-in fully-local digest: `digest_model: ollama:<model>` runs Phase 2 through your own Ollama server — transcript text never leaves the machine
- ✓ Translation at the digest layer: digests in any language, or a faithful full-transcript translation
- ✓ Optional preferences file for standing habits — zero setup required
- ✓ Interpreter auto-selection: backend installed in another Python (e.g. Homebrew) is found and used automatically; `--doctor` diagnoses the environment
- ✓ Apple Podcasts fallback built in: when yt-dlp's extractor fails, episodes resolve via the iTunes lookup API — cache identity stays on your original link; a show link (no episode id) automatically uses the latest episode
- ✓ Opt-in frame extraction for video sources: scene-detection slide capture, or stills at exact timestamps — video fetched at ≤720p and deleted after extraction; frames share the transcript's cache entry
- ✓ Subtitle export: `--format srt` / `--format vtt` write a standard subtitle file with segment timestamps alongside the transcript, on any of the four backends
- ✓ Transcript correction: before each digest, a model proposes sound-alike fixes, `correct.py` checks them and applies them to a cached copy; the original transcript is never edited (optional `pypinyin`, `jellyfish`)
- ✓ Name correction: names that sound like another word (真真 heard as 珍珍) are fixed in the digest from the source's own title, channel, show/channel author, description, chapters and tags, plus an optional glossary — every change is listed, and the transcript is never edited
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

The skill follows the open SKILL.md standard, so it works in Codex as-is. Codex's plugin
command reads the same marketplace (run these in a terminal, not inside a Codex session):

```bash
codex plugin marketplace add AugustusW/audio-tldr-skill
codex plugin add audio-tldr@audio-tldr-skill
```

Installed this way, the skill is listed as `audio-tldr:audio-tldr` (checked with codex-cli
0.162.1: installs, and Codex lists the skill; the end-to-end Codex runs before 1.0 used the copy
below). Or copy the skill folder into Codex's skills directory:

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
| Python 3.10+ | runs the transcription script | macOS's built-in `python3` is 3.9 and not supported — `brew install python` or `uv python install 3.12`; Windows: python.org installer |
| `yt-dlp` | download audio from URLs | `pip install yt-dlp` or `brew install yt-dlp` |
| `ffmpeg` | audio extraction/conversion | `brew install ffmpeg` / `apt install ffmpeg` |
| **One** whisper backend | speech-to-text | table below |
| `pypinyin`, `jellyfish` (optional) | sound check for transcript correction | `pip install pypinyin jellyfish`, into the Python that has your whisper backend |

Whisper backends, in the order the skill auto-detects them:

| Backend | Best for | Install | Default model |
|---|---|---|---|
| [mlx-whisper](https://pypi.org/project/mlx-whisper/) | Apple Silicon (fastest) | `pip install mlx-whisper` | `large-v3-turbo` |
| [faster-whisper](https://pypi.org/project/faster-whisper/) | Cross-platform GPU/CPU | `pip install faster-whisper` | `large-v3-turbo` |
| [whisper.cpp](https://github.com/ggerganov/whisper.cpp) | CPU, no Python deps | `brew install whisper-cpp` + set `AUDIO_TLDR_WHISPER_CPP_MODEL` | (your model file) |
| [openai-whisper](https://pypi.org/project/openai-whisper/) | Original CLI | `pip install openai-whisper` | `large-v3-turbo` |

Local files don't need `yt-dlp` — only a whisper backend.

For URL sources, make sure you have the right to download and process the content, and comply
with the source site's terms and your local copyright law.

### Choosing a model

The default is `large-v3-turbo` on every backend (whisper.cpp excepted — its model is the
`AUDIO_TLDR_WHISPER_CPP_MODEL` file). On CPU-only machines this favors quality over speed —
drop to `small` if transcription is too slow. Override per run with `--model`, or persistently
with `AUDIO_TLDR_MODEL` (the flag wins). Bare names are mapped per backend (mlx gets the
`mlx-community/whisper-` prefix automatically; a full HF repo path is used as-is; named
aliases map to the backend's community conversion — see below):

| Situation | Suggested model |
|---|---|
| CPU / quick tests | `small` |
| General Chinese summaries | `medium` |
| Names, jargon, accuracy-critical | `large-v3` |
| Capable GPU, speed + quality | `large-v3` or `large-v3-turbo` |
| Taiwanese Mandarin accent, zh-en code-switching | `breeze-asr-25` (see below) |

```powershell
python3 scripts/transcribe.py --model small "<source>"   # per run
$env:AUDIO_TLDR_MODEL = "large-v3"    # persistent; PowerShell (bash/zsh: export AUDIO_TLDR_MODEL=large-v3)
```

The cache is keyed by source, not model — to re-transcribe an already-cached source with a
different model, add `--force`.

**Taiwanese Mandarin (`breeze-asr-25`):** [MediaTek Breeze-ASR-25](https://huggingface.co/MediaTek-Research/Breeze-ASR-25)
is a Whisper-large-v2 fine-tune optimized for Taiwanese Mandarin and Mandarin-English
code-switching (Apache 2.0). The alias resolves to a community conversion per backend —
mlx-whisper: [`eoleedi/Breeze-ASR-25-mlx`](https://huggingface.co/eoleedi/Breeze-ASR-25-mlx),
faster-whisper: [`SoybeanMilk/faster-whisper-Breeze-ASR-25`](https://huggingface.co/SoybeanMilk/faster-whisper-Breeze-ASR-25)
(~3 GB download on first use). There is no openai-whisper conversion — the script reports
that instead of guessing. whisper.cpp users can point `AUDIO_TLDR_WHISPER_CPP_MODEL` at one
of the community GGML conversions on Hugging Face.

Trade-offs, from one A/B run we did on a 52-minute Taiwanese-Mandarin finance podcast
(Apple M4 Pro, mlx-whisper backend, single episode — not a benchmark suite): Breeze-ASR-25
was noticeably better on Taiwanese names, finance terms, and mixed zh/en passages, but ran
about 3× slower than `large-v3-turbo` (≈5× realtime vs ≈15×, its backbone is the bigger
large-v2), produced almost no punctuation, and emitted English words in lowercase. The
default stays `large-v3-turbo`; reach for `breeze-asr-25` when getting Taiwanese-Mandarin
names and terminology right matters more than speed and punctuation.

No model fixes a name that sounds exactly like another word. On a 26-minute Taiwanese vlog
(2026-10-06, same machine), the host's name 真真 came out as 珍珍 on `large-v3-turbo`, on
`large-v3-turbo` with the title and channel passed as the initial prompt, and on
`breeze-asr-25` alike; Breeze fixed some misheard place names and broke one the default had
right. That is what [Name correction](#name-correction) is for.

**Optional — Traditional Chinese:** whisper often emits Simplified Chinese. `pip install opencc`
and Chinese transcripts are converted to Taiwan Traditional automatically — including
common-phrase localization (`s2twp`, e.g. 軟件→軟體) — plus the model is biased toward
Traditional vocabulary. Not installed → transcripts are left as-is.

The conversion is applied per segment, and only to segments that actually contain
Simplified characters. A segment already written in Traditional is passed through
untouched, so words that are valid in both scripts (干, 里, 吃) and phrases the
localization table would otherwise rewrite (文件 as "document") keep what the speaker
said.

### Windows notes

The full flow has been verified manually on Windows, in Claude Code and Codex, on versions
before v0.9.0. v0.9.0 itself was checked on 2026-10-06 (Windows 11 Pro, Python 3.12.11,
faster-whisper 1.2.1 on an RTX 5080): the full test suite, `--doctor`, real English and Chinese
transcription with Traditional output, a cache hit, and `--format srt`. v1.0 was run end to end
on 2026-10-11 in both Claude Code and Codex (download, transcription, transcript correction,
digest, `.srt`/`.vtt`, cache hits); see the CHANGELOG for what that run found and fixed. Install
with PowerShell:

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
- **Smart App Control may block `yt-dlp.exe`** — the prebuilt binary is unsigned, and Smart App
  Control silently refuses to run it (Event Viewer shows a CodeIntegrity event 3077 for the
  file). It does not prompt; `yt-dlp` just never runs. Fix: install yt-dlp into the same
  Python that runs the skill — `py -3 -m pip install yt-dlp`. On Windows the scripts run it as
  `python -m yt_dlp` whenever the module is installed, and the signed `python.exe` is allowed.
  A `yt-dlp.cmd` shim is **not** used (before v0.9.1 it was documented here but never actually
  invoked): batch files run through `cmd.exe`, where an `&` in a URL splits the command line.
- **Python shims blocked in an agent sandbox** — with Smart App Control or another application
  control policy on, launcher shims such as `%USERPROFILE%\.local\bin\python3.12.exe` (created
  by uv) can be refused inside Codex's sandbox (`os error 4551`). Point the agent at the real
  interpreter instead: set `AUDIO_TLDR_PYTHON` to the `python.exe` of the environment that has
  the backend (for example a venv's `Scripts\python.exe`). Switching interpreters on Windows runs
  the script as a child process and returns its output and exit code (before v1.0 the caller got
  empty output and exit 0).
- **YouTube downloads fail with HTTP 403** — recent yt-dlp needs a JavaScript runtime for
  YouTube. Install [Deno](https://deno.com/), or, if Node.js is already installed, add
  `--js-runtimes node` to yt-dlp's config file (`%APPDATA%\yt-dlp\config.txt`).
- **Quote comma lists in PowerShell** — `frames.py --at 90,215,10:05` gets split by PowerShell
  into three separate arguments before Python ever sees it (commas are not special-cased inside
  quotes). Always quote: `--at "90,215,10:05"`.

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

> **Pairs well with [sharedoc-mcp](https://github.com/AugustusW/sharedoc-mcp)** — once the digest
> is written, "share this as a doc" turns it into a link you can hand to anyone
> (append, extend, or revoke it later).

### Frames (optional)

```
> summarize this talk and grab the slides: https://youtu.be/xxxx
> screenshots at 1:30 and 12:05 from ~/Videos/keynote.mp4
```

Asking for screenshots / slides runs `scripts/frames.py`: ffmpeg scene detection captures
frames where the picture visibly changes (`--threshold`, `--min-gap`, `--max-frames`,
JPEG quality via `--quality`), or
`--at 90,12:05` extracts stills at exact timestamps (e.g. to illustrate a digest timeline).
Off by default — plain summarize requests never download video. For URLs the video is
fetched at ≤720p and deleted right after extraction (`--keep-video` keeps it); local files
are used in place and never modified. Frames and their `manifest.json` live in the same
cache entry as the transcript, so repeated requests are instant. Pure logic is covered by
automated tests; real-video extraction is verified manually per release.

### Subtitles (SRT/VTT)

```
> transcribe this and give me subtitles: https://youtu.be/xxxx
> srt file for ~/Videos/keynote.mp4
```

```bash
python3 scripts/transcribe.py --format srt "<source>"   # transcript.srt, standard SRT
python3 scripts/transcribe.py --format vtt "<source>"   # transcript.vtt, standard WebVTT
```

`--format` defaults to `txt` (unchanged). `srt`/`vtt` additionally write a subtitle file with
segment-level timestamps next to `transcript.txt` — the plain transcript is unaffected either
way. All four whisper backends support it. Segment data is cached once, so asking for the
*other* subtitle format later (`vtt` after an earlier `srt` run, or vice versa) reformats
from the cached segments instantly — no re-transcription. A cache entry from before this
feature (or last transcribed with `--format txt`) has no segment data to build subtitles
from: the script reports that clearly and names the fix (`--force --format srt`, or `vtt`, to
re-transcribe with timestamps) rather than silently guessing or downgrading the request.

## How it works

Two phases, deliberately separated:

1. **Transcribe** (`scripts/transcribe.py`) — resolves a cache key (normalized URL or file
   content hash), returns instantly on a hit; otherwise downloads via yt-dlp, transcribes with
   the best available whisper backend, and caches `transcript.txt` + `meta.json` under
   `~/.cache/audio-tldr/<sha256>/`. For URL sources it also keeps the source's own details
   (title, channel, description, chapters, tags) in `context.json`, from the metadata it
   fetched anyway.
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
  Claude session — exactly like asking Claude to read any local file. **Exception:** set
  `digest_model: ollama:<model>` and the digest runs through your own local Ollama server
  instead — the transcript text never leaves the machine either, for a fully local pipeline
  (traded against a small local model's lower digest quality). See
  [Digest templates](#digest-templates).
- **Cached transcripts are unencrypted plaintext, kept indefinitely by default**, under
  `~/.cache/audio-tldr/`. After processing sensitive content, `--clear` that entry, or configure
  a retention period.
- **The corrected transcript is plaintext too.** `transcript.corrected.txt`, `corrections.json`
  and `reference.md` sit next to the transcript in the cache folder and follow its retention
  setting. See [Transcript correction](#transcript-correction).
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
model: large-v3
```

| field | default | meaning |
|---|---|---|
| `output_dir` | `./audio-tldr-output` | where digest files are saved |
| `timeline` | `on` | include a timeline section in digests when content warrants it |
| `auto_delete_audio` | `on` | delete downloaded audio after transcription; `off` keeps the mp3 in the cache entry |
| `output_format` | `md` | digest file format, `md` or `html`; a per-request choice always wins |
| `model` | `large-v3-turbo` | whisper model for transcription (passed as `--model`); a per-request choice always wins |
| `digest_model` | (platform default) | model for the digest — unset = platform default subagent (Claude Code: `sonnet`; Codex: `GPT-5.6 Terra`); a model name pins the subagent model; `ollama:<model>` (e.g. `ollama:llama3.2`) runs the digest locally through your own Ollama server instead — see below; `off` = digest inline on the current agent (typically pricier) |

The file is read by the agent (Claude Code and Codex share it) — the install never asks you to
set it up, and defaults apply whenever it's absent.

## Digest templates

Three built-in templates shape the digest output — name one ("digest this as
meeting minutes") or pick from the menu when asked:

| Template | What you get |
|---|---|
| `meeting-minutes` | Meta, topics discussed, decisions, action items, open questions |
| `key-summary` | Key takeaways, one-paragraph summary, optional timeline (the default) |
| `analysis-report` | Arguments with evidence, data points, perspectives, implications |

The timeline in `key-summary` appears only when the `timeline` preference is not
`off`, the source runs over 20 minutes, and the transcript has clear topic shifts.

**Build your own:** drop a markdown file in `~/.config/audio-tldr/templates/` —
frontmatter (`name`, `description`) plus section instructions; same name overrides a
built-in, a new name becomes a new menu option. Easiest start: copy a built-in from
`skills/audio-tldr/templates/` and edit (e.g. change the timeline threshold). You can
also just describe a format in conversation — the skill offers to save it for reuse.
Your templates live outside the skill folder, so skill updates never touch them.

**Cheaper digests:** on platforms with subagents the digest runs on a cheaper model
by default (Claude Code: `sonnet`; Codex: `GPT-5.6 Terra`) — see the `digest_model`
preference to pin a model or turn this off (`off` = digest inline).

**Fully-local digest (Ollama):** set `digest_model: ollama:<model>` (e.g.
`ollama:llama3.2`) and Phase 2 runs through your own local
[Ollama](https://ollama.com) server via `scripts/digest.py` instead of any agent
subagent — the transcript text never leaves the machine either, on top of the
already-local transcription pipeline. Requires Ollama installed, `ollama serve`
running, and the model already pulled (`ollama pull <model>`) — same
user-responsibility rule as the whisper backends, nothing is installed or pulled
automatically. Server address defaults to `http://localhost:11434`; override with
`AUDIO_TLDR_OLLAMA_HOST` if Ollama runs on another machine on your network. If the
server is unreachable or the model isn't pulled, the agent reports the specific
error and stops — it never silently falls back to an agent-session digest, since
that would defeat the point of choosing this mode. Tradeoff: a small local model's
digest quality is generally below the subagent path (sonnet / GPT-class models).

## Transcript correction

Speech recognition writes names and terms as words that sound like them. Before each digest of
a Chinese or English transcript, a model proposes corrections, `correct.py` checks them, and
the digest reads the corrected copy.

- **How it works.** The model only returns a list of edits (wrong text, right text, the words
  around it). It never rewrites the transcript. Each edit is accepted only if it passes every
  check below; one that fails any of them is dropped and the rest still apply.
  - *Sound.* Chinese: same syllable count, and at most one third of the syllables differ
    (toneless pinyin via `pypinyin`; zh/z, ch/c, sh/s, ing/in, eng/en, ang/an and l/n count as
    the same; for a heteronym the closest reading is used). English: compared word by word when
    both sides have the same number of words (metaphone via `jellyfish`, distance at most
    0.45), as a whole string otherwise.
  - *Shape.* At most 24 characters each side; the place must be unique (or the edit is marked
    "all occurrences"); a number character (digit or Chinese numeral) may only be replaced by a character with the identical reading, tones ignored; otherwise the edit is rejected;
    an edit that mixes Chinese and Latin script is rejected.
  - *Limits.* All edits together may change at most 5% of the text (or 24 characters,
    whichever is larger), and an edit applied in 5 or more places is listed at the end of the
    digest so you can check it.
  - *Verification.* After applying, the result is checked again from the other direction. If
    anything does not line up, the whole corrected copy is discarded and the digest uses the
    original.
- **Install.** `pip install pypinyin jellyfish` (optional), into the Python that has your whisper
  backend: `--doctor` lists each interpreter with `module_backend`, `pypinyin` and `jellyfish`,
  and `correct.py` switches to the one that has them, the same way `transcribe.py` switches to the
  backend (`AUDIO_TLDR_PYTHON` overrides both). With Homebrew Python, `pip` refuses (PEP 668):
  use `<that python> -m pip install --break-system-packages pypinyin jellyfish`, or install the
  backend and both packages into a virtual environment and point `AUDIO_TLDR_PYTHON` at it. Without a package, edits in that script are not checked and not applied, and the
  digest runs as before. `pypinyin` covers Chinese, `jellyfish` English. Installing one later
  triggers a single recompute for transcripts that needed it.
- **Where it is stored.** In the transcript's cache folder: `transcript.corrected.txt` (the
  corrected copy), `corrections.json` (every edit, accepted or rejected, with the reason), and
  `reference.md`. For subtitles, `transcript.corrected.srt` / `.vtt` are made when a digest
  asks for them. Correction never modifies `transcript.txt`. (1.0 adds line breaks between
  Whisper segments (at sentence ends only inside long lines) to a transcript cached by an older version the first time it reads it, with no
  character changes. Only a strict UTF-8 file without a BOM is upgraded; a BOM or non-UTF-8
  (e.g. Windows code page) cache is left as it is and still reads as one line.) These files are plaintext
  like the transcript and follow the same retention setting.
- **Reuse.** Digesting the same source again reuses the corrected copy. It is redone when the
  transcript, your glossary or the source details change, or when a newer correction rule
  ships; the transcription itself is never redone for this.
- **Privacy mode.** With `digest_model: ollama:<model>` the corrections are proposed by your
  local Ollama model too, so the transcript still never leaves the machine. If Ollama fails
  (including a context too small for the request), the agent shows the error and
  stops.

  A long transcript is digested in sections and the section results are merged; a `note:` on
  stderr says so, with the number of requests. `--whole-text` stops with an error instead of
  using sections. Every request's reply may use the context left after its prompt (at least 4096 tokens). The section and merge steps ask the model not to think (Ollama `think: false`, ignored by models without thinking); the final digest uses the model's default. The context size is `AUDIO_TLDR_OLLAMA_NUM_CTX`, by default 32768 or the
  model's own limit, whichever is smaller.

  Timestamp check: when the input is a subtitle file, bracketed `[MM:SS]` / `[H:MM:SS]`
  timestamps in the digest that do not appear in the subtitle are removed before output, and a
  stderr note gives the count. Plain-text input is not filtered, and other forms (ranges,
  parentheses) are not checked.
- **Usage log.** Each correction and each digest adds one line to `usage.jsonl` in the same
  cache folder: phase (`correct` or `digest`), path (`subagent`, `ollama` or `inline`), model,
  and token counts (`input`, `output`, `cache_write`, `cache_read`, `total`). A field the
  platform does not report is `null`, never an estimate: a subagent run in Claude Code or Codex
  only reports its total, a local Ollama run reports input and output, and a digest the main
  model writes itself (`digest_model: off`) has no per-call count at all. Only numbers and model
  names are written, never transcript or digest text. Re-transcribing with `--force` keeps this
  file.
- **Languages.** Chinese (Mandarin and Cantonese) and English. The language the backend recorded
  may be a code, a region tag (`zh-TW`) or a name (`Chinese`); anything else, such as Japanese,
  is skipped.
- **Known limitation.** Words that sound alike but mean different things cannot be told apart
  by sound: in the calibration set, Paris → Prague passes the sound check. The other limits
  (24 characters, a unique place, the 5% total (24 characters at minimum), edits applied 5 or more times listed in the
  digest) bound that risk; they do not remove it. The English thresholds were calibrated mostly
  on hand-curated pairs; the Chinese ones on real recognition errors plus curated boundary
  pairs.
- **Measured effect.** Measured on two podcast clips (Chinese, about 22 minutes in total) with no
  glossary; the reference given to the model was the episode title, channel, description and the
  show's author (the host names the show lists). The correction instructions and the source
  details were extended after earlier measurements; the numbers here are from the latest re-run.
  Character error rate (CER, pooled over both clips, against a hand-proofread reference) went
  from 6.23% to 5.10-5.18% with `claude` (3 runs) on the mlx-whisper transcript, and from 7.35%
  to 6.56-6.82% on the faster-whisper one. Names of people, places and products that appear in
  the reference were written correctly 13 of 33 times before and 29-32 after (mlx), 21 of 33
  before and 30-32 after (faster-whisper); part of that gain comes from the author names now
  being in the reference. With `codex` (1 run each) CER was 5.18% and 6.44%; with a local Ollama
  model (`gemma4:26b`, mlx transcript, 1 run) 5.66%, names 22 of 33. No edit made the score worse
  against the reference in any of these runs. On an English public sample (`canterville-en`) the
  model proposed nothing and the text did not change. Limits: only these two clips, and the
  references were proofread from two models' drafts, so they can be wrong too. This is what
  happened on these clips, not a guarantee for other audio.

## Name correction

Speech recognition writes what it hears. A name that sounds like another word comes out as
that word, and no model can tell them apart from the audio alone. The source usually spells
the name right somewhere, though: in the title, the channel name, the show or channel author (host names are often there), the description, the
chapter titles, the tags.

So the digest step gets a reference to check spellings against:

- **Source details** (URL sources): kept in the cache entry as `context.json`. A YouTube
  video's come from yt-dlp; an Apple Podcasts episode's from the iTunes lookup (show name, show author and
  episode notes, where guests are usually named). Entries cached before v0.9.0 fetch them once
  on their next hit; if that fails, the next try is a week later.
- **Your glossary** (optional): `~/.config/audio-tldr/glossary.txt` — one term per line,
  optionally followed by `|` and how it gets misheard:

  ```
  真真 | 珍珍
  真奈特 | 珍耐特, 真 night
  Breeze-ASR
  ```

The digest model is told to be conservative: use the reference's spelling when a word sounds
like one of its names, fix other mishearings only when the context leaves no doubt, and
otherwise leave the transcript's word alone. Every change is listed in one line at the end of
the digest. The transcript file itself is never edited.

The source details are written by whoever uploaded the media, so they are treated like the
transcript: as data, never instructions. They reach the digest model through a file rather
than its prompt, folded to single lines and fenced by a random marker, and may only decide
how a word is spelled.

## Cache & configuration

The cache is **kept forever by default** — nothing is auto-deleted unless you opt in.

Ask Claude, or run `scripts/transcribe.py` directly:

| Command | What it does |
|---|---|
| `--language <code>` | force the transcription language (e.g. `zh`); default auto-detect |
| `--model <name>` | whisper model for this run — see [Choosing a model](#choosing-a-model) |
| `--cache-info` | list cached transcripts + sizes (JSON) |
| `--clear "<source>"` | delete one entry |
| `--clear-all --yes` | delete everything |
| `--set-retention <days>` | auto-prune entries older than N days (`off` = keep forever) |
| `--ack-retention-notice` | stop the one-time "where your transcripts are kept" notice (the skill runs this after telling you) |
| `--force` | re-transcribe one source, ignoring cache |
| `--keep-audio` | keep the downloaded mp3 in the cache entry (default deletes it after transcription) |
| `--doctor` | JSON environment diagnosis: Python path/version, backend & tool visibility (including exactly how yt-dlp will be launched), other interpreters that have a backend, MLX Metal availability |
| `--format txt\|srt\|vtt` | output format (default `txt`, unchanged); `srt`/`vtt` also write a subtitle file with segment timestamps — see [Subtitles](#subtitles-srtvtt) |

Environment variables:

| Variable | Purpose |
|---|---|
| `AUDIO_TLDR_MODEL` | override the whisper model for the active backend (`--model` beats it) |
| `AUDIO_TLDR_WHISPER_CPP_MODEL` | path to a ggml model file (enables the whisper.cpp backend) |
| `AUDIO_TLDR_ZH_CONVERT` | Chinese conversion: `off`, or an OpenCC config (default `s2twp` — Taiwan Traditional incl. common phrases) |
| `AUDIO_TLDR_PYTHON` | pin the Python interpreter the script runs under (wins over auto-probing). Useful when your whisper backend lives in a non-default Python (e.g. Homebrew 3.12) |
| `AUDIO_TLDR_OLLAMA_NUM_CTX` | Context size (`num_ctx`) for Ollama requests; default 32768 or the model's own limit, whichever is smaller. A transcript that does not fit is digested in sections |
| `AUDIO_TLDR_OLLAMA_HOST` | Ollama server base URL used by `digest_model: ollama:<model>` (default `http://localhost:11434`); set when Ollama runs on another machine on your network. `digest.py --ollama-host` overrides it for one call |
| `AUDIO_TLDR_GLOSSARY` | path to the [name-correction](#name-correction) glossary (default `$XDG_CONFIG_HOME/audio-tldr/glossary.txt`, else `~/.config/audio-tldr/glossary.txt`) |

## Develop

```bash
git clone https://github.com/AugustusW/audio-tldr-skill.git
cd audio-tldr-skill
python3 -m pytest tests/   # 691 unit tests, no network or model needed
```

Transcription quality is measured with `scripts/asr_eval.py` (needs `opencc`, `ffmpeg`, and a
whisper backend; not part of the skill):

```bash
python3.12 scripts/asr_eval.py run --samples public --repeat 3 --label baseline
python3.12 scripts/asr_eval.py compare <baseline.json> <new.json>   # exit 1 on a regression
```

The public samples in `tests/fixtures/eval/` are public-domain LibriVox recordings plus
ffmpeg-generated tones and silence, and check the tool itself; references mark names as `〔name〕` (mark every occurrence). Quality decisions are made
on a private set of real podcast clips kept in the upstream repository.

Versioning: write the [CHANGELOG](./CHANGELOG.md) entry for the new version, then run

```bash
python3 scripts/release.py 0.7.4      # --dry-run reports what it would do, and writes nothing
```

It bumps `version` in `.claude-plugin/plugin.json` and `.claude-plugin/marketplace.json`, rewrites
the version and the test count in both READMEs, refuses to go on unless the full suite passes, and
only then commits, tags, pushes, and publishes the
[GitHub Release](https://github.com/AugustusW/audio-tldr-skill/releases) with that CHANGELOG
section as its notes. `tests/test_docs.py` guards the half of that which lives in the repository:
the suite fails if either README's Status version, either README's stated test count, the
marketplace version, or the newest CHANGELOG entry falls out of step with `plugin.json`.
**To get update notifications**: Watch this repo (Custom → Releases), or — if you installed as a
Claude Code plugin — run `/plugin` and update from the marketplace (it compares the version above).
Manual-copy installs have no auto-update: re-copy the skill folder after a new release.
Your preferences, custom templates (`~/.config/audio-tldr/`), and cache
(`~/.cache/audio-tldr/`) all live outside the skill folder — updating never touches them.

## Compatibility

From 1.0, every 1.x release keeps what lives on your disk working:

- **Cache**: entries made by 0.9.x or any 1.x are read and reused by every later 1.x — including after you move or copy the whole cache folder. An entry is quietly brought up to date the first time 1.x uses it, and going back to 0.9.x still finds it (if you moved the cache, let 1.x use an entry once before going back).
- **Windows caveat**: on Windows with a non-UTF-8 system code page and Python 3.14 or older, going back to 0.9.x can break 0.9.x's local-Ollama digest for transcripts that 1.x created (1.x writes transcripts as UTF-8); finding cached entries still works.
- **Glossary**: same location, same one-term-per-line format.
- **Settings**: `config.json` and `~/.config/audio-tldr/` (preferences, templates) keep their keys and locations; new versions only add keys.

Not covered: the scripts' command-line flags and output fields, built-in template wording, and the exact text of transcripts and digests. Those can change between releases and are listed in the [CHANGELOG](./CHANGELOG.md).

## Status

v1.0.0 ([CHANGELOG](./CHANGELOG.md)) — core logic is covered by 691 offline unit tests (yt-dlp,
whisper backends, cache, OpenCC, ffmpeg/ffprobe frame extraction, and the Ollama HTTP endpoint
are mocked; no network or models needed). The full flow has been manually verified (2026-07-19:
real YouTube download, transcription, cached re-digest, Chinese conversion, `--keep-audio`,
output-folder digests in md/html, transcript translation, interpreter auto-selection from
`/usr/bin/python3`, and the Apple Podcasts fallback end-to-end —
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
downloads, the other three backends, and Windows (verified manually there; see
[Windows notes](#windows-notes)). Codex support follows the open SKILL.md
standard; the transcription core was verified end-to-end inside Codex on 2026-07-19 (a real
53-min podcast downloaded, transcribed, and cache-hit, including the interpreter
auto-selection path). Digest-layer features (output folder, translation, preferences) have so
far been exercised in Claude Code only. SRT/VTT subtitle export (v0.6.0) is covered by unit
tests on all four backends' segment-capture and formatting logic; end-to-end subtitle output
from a real transcription has not yet been manually verified on every backend. The Ollama local
digest mode (v0.6.0) is covered by unit tests against a mocked HTTP endpoint (request shape,
response parsing, unreachable-server and model-missing errors); it has not yet been manually
verified against a real Ollama server. Frame extraction (v0.5.0) is covered by unit tests that
stub ffmpeg and ffprobe rather than invoking them; the past-end-timestamp behavior fixed in
v0.7.1 was measured against ffmpeg 8.1, and other versions may exit differently. Name
correction (v0.9.0) was checked end-to-end on one YouTube video with a `sonnet` digest: in five
runs, names backed by the reference were fixed and listed every time, a correct place name was
left alone, and the transcript was unchanged; without the reference the name stayed wrong. In
two of the five runs a place name fixed from context alone was not listed, once wrongly, so the
change list is what the model reports rather than a guaranteed diff; the Apple Podcasts context path, the Ollama path with `--context`, and
small local models' handling of the rule are covered by unit tests or not yet exercised. Possible next:
speaker diarization. Issues and PRs welcome.

## License

MIT. See [LICENSE](./LICENSE).

---

> Long content is worth hearing once — by your machine, not by you.
