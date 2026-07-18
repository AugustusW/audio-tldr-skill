# audio-tldr

A [Claude Code](https://claude.com/claude-code) skill that turns **videos, audio files, and podcasts** into **key takeaways + a summary** — transcribed locally, cached forever, never transcribed twice.

```
URL or file ──▶ Phase 1: transcribe (local whisper, cached on disk)
                        │
                        ▼
                Phase 2: digest (Claude reads the transcript)
                        │
                        ▼
        3–7 key takeaways + summary (+ timeline for long content)
```

Ask for a different angle later ("focus on the investment advice") and it re-digests from cache — **zero re-transcription**.

## Prerequisites

Everything runs locally; nothing is uploaded anywhere.

| Requirement | Why | Install |
|---|---|---|
| Python 3.9+ | runs the transcription script | usually preinstalled |
| `yt-dlp` | download audio from URLs (YouTube, podcasts, …) | `pip install yt-dlp` or `brew install yt-dlp` |
| `ffmpeg` | audio extraction/conversion | `brew install ffmpeg` / `apt install ffmpeg` |
| **One** whisper backend (pick one below) | speech-to-text | see table |

Whisper backends, in the order the skill auto-detects them:

| Backend | Best for | Install |
|---|---|---|
| [mlx-whisper](https://pypi.org/project/mlx-whisper/) | Apple Silicon (fastest) | `pip install mlx-whisper` |
| [faster-whisper](https://pypi.org/project/faster-whisper/) | Cross-platform (GPU/CPU) | `pip install faster-whisper` |
| [whisper.cpp](https://github.com/ggerganov/whisper.cpp) | CPU, no Python deps | `brew install whisper-cpp`, then set `AUDIO_TLDR_WHISPER_CPP_MODEL=/path/to/ggml-*.bin` |
| [openai-whisper](https://pypi.org/project/openai-whisper/) | Original CLI | `pip install openai-whisper` |

Local audio/video files don't need `yt-dlp` — only a whisper backend.

**Optional — Traditional Chinese output:** whisper often emits Simplified Chinese for Chinese audio. Install [`opencc`](https://pypi.org/project/OpenCC/) (`pip install opencc`) and Chinese transcripts are automatically converted to Taiwan Traditional (plus the model is biased toward Traditional vocabulary via prompt). Not installed → transcripts are left as-is. Configure with `AUDIO_TLDR_ZH_CONVERT`: `off` to disable, or any OpenCC config name (`s2tw` default, `s2twp`, `t2s`, …).

## Install

**Option A — copy the skill (simplest):**

```bash
git clone https://github.com/AugustusW/audio-tldr-skill.git
cp -r audio-tldr-skill/skills/audio-tldr ~/.claude/skills/
```

Invoke with `/audio-tldr` (or just ask Claude to summarize a video — it auto-triggers).

**Option B — install as a plugin:**

```
/plugin marketplace add AugustusW/audio-tldr-skill
/plugin install audio-tldr@audio-tldr-skill
```

Invoke with `/audio-tldr:audio-tldr`. Both options can coexist — plugin skills are namespaced.

## Usage

```
> summarize https://www.youtube.com/watch?v=xxxx
> give me the key points from this podcast: https://podcasts.apple.com/...
> /audio-tldr ~/Downloads/meeting-recording.m4a
> (later) same video, but focus only on what they said about pricing
```

The last one re-uses the cached transcript — instant, no re-transcription.

## Cache & configuration

- Transcripts live in `~/.cache/audio-tldr/<sha256>/` (`$XDG_CACHE_HOME` respected) and are **kept forever by default**.
- `--force` re-transcribes ignoring cache.
- Cache management (just ask Claude, or run `scripts/transcribe.py` directly): `--cache-info` lists entries + sizes (JSON), `--clear "<source>"` removes one entry, `--clear-all --yes` removes everything, `--set-retention <days>` enables auto-pruning of old entries (`off` to go back to keep-forever). Nothing is ever auto-deleted unless you set a retention.
- `AUDIO_TLDR_MODEL` — override the whisper model (default: `mlx-community/whisper-large-v3-turbo` on mlx, `small` elsewhere).
- `AUDIO_TLDR_WHISPER_CPP_MODEL` — path to a ggml model file (required to enable the whisper.cpp backend).
- `AUDIO_TLDR_ZH_CONVERT` — Chinese conversion config: `off`, or an OpenCC config name (default `s2tw`; requires `pip install opencc`).

## FAQ

**Why two phases?** Transcription is the expensive part (minutes); digesting is cheap (seconds). Caching the transcript means asking "summarize it differently" costs nothing.

**How long does transcription take?** Roughly 0.1–0.5× realtime depending on backend and hardware — a 30-minute podcast typically takes 3–10 minutes on first run, instant afterwards.

**Privacy?** Everything is local: download, transcription, cache. The transcript is only read by your own Claude session when digesting.

---

## 繁體中文

**audio-tldr** 是一個 Claude Code skill：把影片 / 音檔 / podcast 轉成**重點條列 + 摘要**。轉錄在本機執行並永久快取——同一來源永遠不會轉錄第二次；之後要求「換個角度摘要」直接吃快取、秒回。

**前置準備**：Python 3.9+、`yt-dlp`（URL 來源需要）、`ffmpeg`，以及**任選一個** whisper 後端：`mlx-whisper`（Apple Silicon 最快）/ `faster-whisper`（跨平台）/ `whisper.cpp`（需設 `AUDIO_TLDR_WHISPER_CPP_MODEL`）/ `openai-whisper`。安裝指令見上方英文表格。

**繁體中文輸出（選配）**：whisper 對中文常輸出簡體。`pip install opencc` 之後，中文逐字稿會自動轉台灣繁體（並以 prompt 引導模型優先用繁體詞彙）；沒裝就維持原樣。`AUDIO_TLDR_ZH_CONVERT=off` 可關閉，或改指定其他 OpenCC 設定（預設 `s2tw`）。

**安裝**（二選一）：
- 手動：clone 後 `cp -r skills/audio-tldr ~/.claude/skills/`，用 `/audio-tldr` 呼叫
- Plugin：`/plugin marketplace add AugustusW/audio-tldr-skill` → `/plugin install audio-tldr@audio-tldr-skill`，用 `/audio-tldr:audio-tldr` 呼叫

**用法**：直接丟 YouTube / podcast 連結或本機音檔路徑，說「幫我摘要」即可；重點 3–7 條 + 一段摘要，超過 20 分鐘的內容附大致時間軸。快取在 `~/.cache/audio-tldr/`，`--force` 可強制重轉。

**快取管理**：預設永久保留、絕不自動刪。直接跟 Claude 說即可——「列出快取」（--cache-info）、「清掉某個來源」（--clear）、「全部清空」（--clear-all --yes，Claude 會先跟你確認）、「逐字稿保留 30 天就好」（--set-retention 30；--set-retention off 回到永久保留）。
