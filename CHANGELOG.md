# Changelog

All notable changes to this project are documented here. **Every release bumps `version` in
`.claude-plugin/plugin.json` and `.claude-plugin/marketplace.json` (kept identical) and adds an
entry below.**

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
