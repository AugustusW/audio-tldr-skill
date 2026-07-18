---
name: audio-tldr
description: Summarize videos, audio files, and podcasts into key takeaways. Give it a YouTube/podcast URL or a local audio/video file — it transcribes locally (cached, never re-transcribes the same source) and distills the transcript into key points and a summary. Use when the user asks to summarize, get key points from, or TL;DR any audio or video content.
---

# audio-tldr

Turn any video / audio / podcast into key takeaways + a summary. Two-phase design: transcription is cached on disk, so re-summarizing (or summarizing from a different angle) never re-transcribes.

## Phase 1 — Transcribe (cached)

Run:

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/transcribe.py" "<URL or file path>"
```

Optional flags: `--language zh` (force language), `--force` (ignore cache).

The script prints one JSON line: `{transcript_path, title, duration, language, backend, cache_hit}`.

**Exit codes — handle them, don't guess:**
- `0` OK → proceed to Phase 2.
- `2` download/backend runtime error → show the stderr message to the user (it contains the fix, e.g. installing yt-dlp/ffmpeg).
- `3` no whisper backend installed → show the install guide printed on stderr, let the user pick a backend, stop here.

Long sources take time (roughly 0.1–0.5× realtime depending on backend). If the source is over an hour, warn the user it may take a few minutes.

## Phase 2 — Digest

Read the file at `transcript_path`, then produce, in the user's language:

1. **Key takeaways** — 3–7 bullets, each a single self-contained insight (not chapter titles).
2. **Summary** — one paragraph, 100–200 words, covering the arc of the content.
3. **Timeline** — only if `duration` > 20 minutes and the transcript has clear topic shifts: 4–8 entries of `~MM:SS topic` (estimate positions proportionally from text position; mark as approximate).

If the transcript is very long (> ~50k words), digest it in sections, then merge.

## Re-digesting

When the user asks for a different angle ("focus on the investment advice", "more detail", "in English"), do NOT re-run Phase 1 — the transcript is cached. Just re-read `transcript_path` and produce a new digest. If you no longer have the path, re-run the Phase 1 command — it returns instantly with `cache_hit: true`.

## Cache management

The cache is kept forever by default. When the user asks about cache or cleanup, use these (same script):

- `--cache-info` — prints JSON: entries (title/source/date/size), total size, current retention. Use it to answer "what's cached / how much space".
- `--clear "<URL or file>"` — delete one entry. Run when the user asks to remove a specific source.
- `--clear-all --yes` — delete everything. Destructive: ALWAYS confirm with the user before running; never run it on your own initiative.
- `--set-retention <days>` — auto-prune entries older than N days on future runs. `--set-retention off` returns to keep-forever. Only set when the user asks for it (e.g. "keep transcripts for 30 days").

Never delete or shrink the cache unless the user explicitly asked.

## Notes

- Prerequisites (yt-dlp, ffmpeg, a whisper backend) are the user's responsibility — see repo README. Never install anything without asking.
- The transcript may contain recognition errors; don't quote it verbatim as ground truth for names/numbers — flag uncertainty when it matters.
