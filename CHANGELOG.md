# Changelog

All notable changes to this project are documented here. **Every release bumps `version` in
`.claude-plugin/plugin.json` and `.claude-plugin/marketplace.json` (kept identical) and adds an
entry below.**

## [0.6.2] - 2026-08-14

### Added

- **`processing_seconds` and a `timings` stage breakdown in transcription output and
  `meta.json`** — `processing_seconds` is the wall-clock of the backend transcription call
  (divide `duration` by it for the realtime factor). `timings` splits the run into
  `download` (URL sources; null for local files), `backend_call` (== `processing_seconds`),
  `postprocess` (repetition collapse + Traditional-Chinese conversion) and `write`
  (cache-file writes, incl. subtitle formatting). Model-load time is not split out — it is
  part of `backend_call` and varies by backend. Entries cached by earlier versions lack
  both fields; cache hits return whatever the original run stored.

## [0.6.1] - 2026-08-11

### Changed (docs only — no code changes)

- `SKILL.md` tightened for agent consumption: script-internal narratives (interpreter
  auto-selection, Apple Podcasts fallback) compressed to "a stderr note explains what happened —
  relay it" with mechanics deferred to the README; the overloaded `digest_model` table cell
  split into its own "Digest model resolution" section; the untrusted-content rule now has one
  named canonical definition (Phase 2) that other sections reference instead of restating.
- No behavior change intended anywhere — same commands, same rules, same guarantees.

## [0.6.0] - 2026-08-11

### Added

- **`--format txt|srt|vtt`** — `scripts/transcribe.py` can now emit standard SRT
  (`HH:MM:SS,mmm -->`) or WebVTT (`WEBVTT` header, `HH:MM:SS.mmm -->`) subtitle files with
  segment-level timestamps, alongside the usual `transcript.txt` (default `txt`, byte-identical
  to pre-0.6.0 behavior — the plain-text path takes no extra work and no extra CLI flags).
  Segment capture is implemented for all four backends: mlx-whisper and faster-whisper expose
  segments directly from their Python API; whisper-cpp (`--output-json`) and openai-whisper
  (`--output_format all`) get them from an additional machine-readable output file, requested
  only when a subtitle format is actually asked for. A backend that genuinely returns no
  segments for a given run fails clearly (exit 2, transcript still cached as text) instead of
  fabricating timestamps.
- **Subtitle caching** — segment data is cached once (`segments.json`) alongside the transcript;
  requesting the *other* subtitle format later (e.g. `vtt` after an earlier `srt` run) reformats
  from the cached segments instantly, no re-transcription. A cache entry with no segment data
  (transcribed before this feature, or last transcribed with `--format txt`) gives a clear
  stderr message naming the fix (`--force --format srt`/`vtt`) instead of silently guessing or
  re-transcribing behind the user's back.
- `SKILL.md` — documents the `--format` flag and both subtitle-request failure modes.
- **`digest_model: ollama:<model>`** — opt-in, fully-local Phase 2 digest. A new
  `scripts/digest.py` relays an agent-assembled instructions block (template/description +
  stated needs + output language + the untrusted-content rule verbatim — the same content the
  subagent-dispatch prompt already carries) plus the transcript to the user's own local
  [Ollama](https://ollama.com) server (`POST /api/chat`, `stream: false`, stdlib `urllib` only,
  no new dependency) and prints back the digest text, so the transcript text never leaves the
  machine either. Server address: `AUDIO_TLDR_OLLAMA_HOST` env var (default
  `http://localhost:11434`), mirroring the `--model`/`AUDIO_TLDR_MODEL` CLI-flag-beats-env-var
  layering already used elsewhere — deliberately the *only* config channel, no parallel
  preferences-file field. An unreachable server or an unpulled model reports a specific error
  and exit 2; it never silently falls back to a subagent or inline digest, since that would
  defeat the reason the mode was chosen. Default behavior (no `digest_model`, or a plain model
  name) is completely unchanged — this is purely additive.
- `SKILL.md` + both READMEs — document the Ollama mode, its honest quality tradeoff (a small
  local model digests worse than the sonnet/GPT-class subagent path), and the privacy rationale
  (the digest phase, not just transcription, becomes zero network egress).
- 44 new offline unit tests (137 total): 25 for subtitle export (as above) + 19 for the Ollama
  bridge — endpoint resolution (CLI/env/default layering), message construction, request/response
  shape against a mocked HTTP endpoint, unreachable-server and model-missing error
  classification, and `main()` wiring (stdin vs. `--instructions-file`, missing-file errors,
  and confirming a failure never prints a fallback digest).

### Fixed

- README.md / README.zh-TW.md `## Status` sections were still frozen at v0.4.0 / 63 tests
  (the v0.5.1 fix only corrected the `## Develop` test count, not `## Status`) — both now read
  v0.6.0 and the current test count.

### Windows notes added (both READMEs)

- Smart App Control can block the unsigned `yt-dlp.exe` shim (CodeIntegrity event 3077, the
  binary silently never runs) — workaround is a `.cmd` shim that calls `python -m yt_dlp` from
  the venv's signed `python.exe`; the `.cmd` file must have **CRLF** line endings or PowerShell
  fails to execute it.
- PowerShell splits an unquoted comma list into separate arguments — `--at` (from `frames.py`)
  needs quotes: `--at "3,10,25"`, not `--at 3,10,25`.

## [0.5.1] - 2026-08-05

### Fixed

- **frames: scene/`--at` mode switching no longer mixes results.** An `--at` request
  is never served from (or merged with) a cached scene-mode manifest: the cache-hit
  check and the incremental-append path now both require a matching `mode`. Previously
  a scene run followed by `--at` returned the scene frames alongside (or instead of)
  the requested timestamps.
- **frames: full rebuilds delete stale JPGs.** Switching modes or using `--force`
  used to leave the previous run's frames on disk unreferenced by `manifest.json`;
  a full rebuild now clears the frames directory first. `--at` partial cache hits
  still only extract the missing timestamps.
- **tests: `pytest` can no longer escape into a real transcription.** On multi-Python
  machines with a whisper backend installed, `transcribe.py`'s interpreter auto-switch
  (`os.execv`) could replace the pytest process and run a real model on a fake test
  file (aborting with exit 134). `tests/conftest.py` now sets the re-exec guard for
  the whole session; re-exec behavior itself stays covered by tests that opt out
  explicitly.
- **Plugin manifests were still `0.4.0` in the v0.5.0 release.** `plugin.json` and
  `marketplace.json` now carry the release version again, per the versioning rule
  above.

### Changed

- README test counts corrected (93 unit tests; the en/zh-TW pages had drifted).

## [0.5.0] - 2026-08-04

### Added

- **`scripts/frames.py`** — opt-in frame extraction for video sources, two modes:
  scene-detection slide capture (`--threshold` / `--min-gap` / `--max-frames` /
  `--quality`) and exact-timestamp stills (`--at 90,12:05`, partial cache hits only
  extract the missing timestamps). Frames + `manifest.json` share the transcript's
  cache entry (same source → same entry); `--force` re-extracts.
- Video lifecycle: URLs are fetched at ≤720p and the video file is deleted right after
  extraction (`--keep-video` keeps it); local files are used in place, never modified.
- `SKILL.md` Phase 1.5 — trigger rules (off by default), digest embedding rules
  (md relative paths / html base64 data URIs), optional vision de-duplication pass,
  untrusted-content rule extended to frame imagery.
- Frames-only cache entries write a minimal `meta.json` so `--cache-info` / `--clear` /
  retention pruning can see them (transcribe.py only lists entries with `meta.json`).
- `tests/test_frames.py` — pure-function and stub-runner coverage (no real
  ffmpeg/yt-dlp in tests).

## [0.4.0] - 2026-07-25

### Added
- **Built-in digest templates** — `meeting-minutes`, `key-summary` (the default digest,
  structure moved from SKILL.md into the template), `analysis-report`; the conversational
  digest prompt now lists the template menu
- **User templates** — drop a markdown file in `~/.config/audio-tldr/templates/`: same name
  overrides a built-in, a new name extends the menu; a format described in conversation can
  be saved as a reusable template
- **Digest via subagent** — on platforms with subagents the Phase 2 digest runs on a cheaper
  model by default (Claude Code: `sonnet`; Codex: `GPT-5.6 Terra`); new `digest_model`
  preference (a model name pins it, `off` = digest inline); falls back to inline digesting
  when dispatch is unavailable
- README (en + zh-TW): Digest templates section, `digest_model` row, update-safety note
- 9 new offline template tests (63 total); `transcribe.py` unchanged

## [0.3.3] - 2026-07-19

### Changed
- **OpenCC default config `s2tw` → `s2twp`** — Chinese transcripts now get Taiwan Traditional
  **with common-phrase localization** (軟件→軟體, 信息→資訊, …), not just character-level
  conversion. Override with `AUDIO_TLDR_ZH_CONVERT` as before (`s2tw` restores the old
  behavior; `off` disables). Test suite: 54 offline unit tests

## [0.3.2] - 2026-07-19

### Added
- **`--model` flag** — pick the whisper model per run (`--model small`). Precedence:
  `--model` > `AUDIO_TLDR_MODEL` env > default. Bare names are mapped per backend (mlx gets
  the `mlx-community/whisper-` prefix automatically; `whisper-`-prefixed names are
  normalized; a full HF repo path is used as-is). whisper-cpp is unaffected (file-based model)
- The cache `meta.json` (and the printed JSON line) now records which `model` produced the
  transcript
- **`model` preference** — set a standing whisper model in
  `~/.config/audio-tldr/preferences.md` (`model: large-v3`); the agent passes it as `--model`.
  An explicit per-request model always wins over the preference

### Changed
- **Default model is `large-v3-turbo` on every backend** — previously faster-whisper and
  openai-whisper defaulted to `small`. On CPU-only machines this favors quality over speed;
  pass `--model small` (or set `AUDIO_TLDR_MODEL=small`) to restore the old behavior
- Test suite grown to 53 offline unit tests (model resolution ×5)

## [0.3.1] - 2026-07-19

### Fixed
- **Apple Podcasts cache identity is now slug- and storefront-independent** — the cache key for
  an Apple episode URL derives from (collection id, episode id) only. Previously the URL path
  slug participated in the key, so the same episode reached via show-page resolution (show-name
  slug) vs a directly copied episode link (episode-title slug) produced two cache entries and
  a duplicate transcription. Existing cache entries keyed under the old scheme are not
  migrated — the first re-run of an Apple source transcribes once into the new key
- **Whisper tail-repetition hallucination collapse** — runs of 3+ consecutive identical phrases
  (the classic decoder loop on trailing silence/music) are collapsed to a single occurrence
  before caching, with a stderr note showing how many characters were removed. Two repeats are
  left untouched (legitimate emphasis). Opt out with `AUDIO_TLDR_DEREPEAT=off`
- **README status corrected** — the Status section claimed Codex end-to-end verification was
  pending; the transcription core was in fact verified inside Codex on 2026-07-19 (real 53-min
  podcast, including the interpreter auto-selection path). The section now states precisely
  what was verified where: digest-layer features remain Claude Code-verified only

### Changed
- Test suite grown to 48 offline unit tests (Apple canonical cache identity ×4, repetition
  collapse ×5)

## [0.3.0] - 2026-07-19

### Added
- **Output folder** — every digest is saved as a file under `./audio-tldr-output/`
  (configurable); transcripts and audio stay in the cache, the output folder holds digests only
- **Conversational digest prompt** — when a request doesn't say how to digest, the agent asks
  in plain text (key takeaways / meeting minutes / detailed summary / action items / Q&A /
  translation / free description). Never a clickable menu — works over plain-text messaging
  channels
- **Translation** — digests in any requested language, plus full-transcript translation as a
  digest style (faithful, chunked for long content, saved to the output folder)
- **Markdown or HTML output** — per-request choice, or the `output_format` preference
  (default `md`); HTML output is a single self-contained file
- **User preferences** — optional `~/.config/audio-tldr/preferences.md` (`output_dir`,
  `timeline`, `auto_delete_audio`, `output_format`), shared across agents; defaults work with
  no setup and the install never asks
- **`--keep-audio`** — keep the downloaded mp3 in the cache entry (default still deletes it
  after transcription); exposed via the `auto_delete_audio` preference
- **Codex support** — portable skill-path wording in SKILL.md, `agents/openai.yaml` metadata,
  and Codex install instructions; cache and preferences are shared with Claude Code
- **Interpreter auto-selection** (from Codex end-to-end validation) — when the invoking Python
  lacks a whisper backend, the script probes common interpreters (Homebrew python3.12/3.13, …)
  and transparently re-execs into one that has it; `AUDIO_TLDR_PYTHON` pins one explicitly.
  Fixes the "backend installed but in another Python" misdiagnosis
- **`--doctor`** — JSON environment diagnosis: Python path/version, backend & tool visibility,
  other interpreters with a backend, MLX Metal availability (distinguishes "not installed" /
  "installed elsewhere" / "importable but sandbox blocks Metal")
- **Apple Podcasts fallback** — yt-dlp's ApplePodcasts extractor can fail (observed HTTP 500);
  episodes now resolve via the iTunes lookup API (collection + storefront country, trackId
  match, RSS enclosure as last resort). The enclosure is transport only: cache identity and
  `source` stay on the original Apple link, `title` uses the episode name, and `media_url`
  records what was actually fetched. A show-page link (no `?i=`) automatically resolves to the
  show's latest episode, with the cache bound to that episode's URL. Specific errors for
  lookup failures and subscriber-only content
- **Codex sandbox guidance** in SKILL.md — backend importable but Metal blocked means a sandbox
  permission issue, not a broken install; agents are told to request approved execution instead
  of reinstalling

### Changed
- `--keep-audio` hardening (from pre-release review): a failed audio move never discards the
  completed transcription (warning on stderr instead); a `--force` re-run without the flag
  preserves and re-references previously kept audio instead of orphaning it; requesting
  `--keep-audio` on a cache hit prints a stderr note instead of silently ignoring the flag
- Output filename slug rule tightened to a strict character allowlist, and metadata is
  explicitly barred from influencing the write destination (prompt-injection surface)
- Privacy docs now cover the output folder (persistent digests incl. translations, no retention,
  `.gitignore` advice)
- Test suite grown to 39 offline unit tests (`--keep-audio` keep / default-delete / local-file
  no-op / `--clear` removes kept audio / move-failure resilience / `--force` preservation /
  cache-hit note / cache-info size)

## [0.2.0] - 2026-07-18

### Added
- Prompt-injection guard in the digest phase: the transcript **and media metadata (title,
  uploader, description)** are treated as untrusted content, never as instructions
- User-directed digests: stated focus / audience / format / length / language override the
  default takeaways+summary structure; offer a free re-cut for long unfocused content
- Windows notes: PowerShell install, winget/Chocolatey, `py -3` fallback (also instructed in
  SKILL.md), CUDA visibility check with its limits, skill path
- Model selection table and `AUDIO_TLDR_MODEL` examples
- Standalone Traditional Chinese README (`README.zh-TW.md`)
- Verified-environment table in Status; usage-rights reminder for URL sources
- This changelog and the version-bump rule

### Changed
- README restructured (tagline / badges / Why? / features / tables)
- Privacy claims made precise: media pipeline is local; the digest phase sends transcript text
  to your Claude session; cached transcripts are unencrypted plaintext kept indefinitely by
  default, with concrete Phase-1-only commands
- Testing claims made accurate: 18 offline unit tests (mocked) + one manual macOS/mlx-whisper
  verification; Windows and other backends not yet verified

## [0.1.0] - 2026-07-18

Initial release: two-phase transcribe (cached by content hash) + digest, whisper backend
auto-detection (mlx-whisper / faster-whisper / whisper.cpp / openai-whisper), optional OpenCC
Traditional Chinese conversion, cache management (`--cache-info` / `--clear` / `--clear-all` /
`--set-retention`, opt-in retention), dual install (manual copy or Claude Code plugin).
