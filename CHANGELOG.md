# Changelog

All notable changes to this project are documented here. **Every release bumps `version` in
`.claude-plugin/plugin.json` and `.claude-plugin/marketplace.json` (kept identical) and adds an
entry below.**

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
