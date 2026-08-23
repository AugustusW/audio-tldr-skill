# Security Policy

## Supported versions

audio-tldr is pre-1.0. Security fixes land on the latest released `0.x` and `main`; older builds
are not separately patched — please update to the latest release.

| Version       | Supported          |
|---------------|--------------------|
| latest `0.7.x`| ✅                  |
| older         | ❌ (please update) |

## Reporting a vulnerability

Please report security issues **privately** — do **not** open a public issue.

- Preferred: this repository's **Security** tab → **Report a vulnerability** (a private GitHub
  security advisory).
- We aim to acknowledge within a few days. Coordinated disclosure is appreciated, and we're happy
  to credit you unless you'd prefer otherwise.

## Security model — please read before reporting

audio-tldr is a skill: installing it gives your agent scripts that run **on your machine, at your
own OS privilege, without a sandbox**. Some behaviour below is inherent to that and is **not** a
vulnerability. See also [Privacy](./README.md#privacy) in the README, which documents the data
flow in detail.

- **It shells out to tools you installed.** `yt-dlp` fetches URL sources, `ffmpeg` converts audio,
  and a whisper backend transcribes. Their bugs — including how they parse hostile media — belong
  upstream. Whisper backends may also download model weights from their own hosts on first use.
- **It fetches what you point it at.** Any URL you pass goes to yt-dlp; Apple Podcasts links are
  resolved through `itunes.apple.com`. There is no allowlist, and none is intended.
- **A transcript is attacker-influenced text that flows into a model prompt.** Summarizing a
  hostile source means an untrusted document reaches your agent — treat a digest of an unknown
  video the way you would treat any web page your agent just read. This is inherent to
  summarization, not a defect we can patch away.
- **Transcripts and digests persist in cleartext.** Transcripts are cached under
  `~/.cache/audio-tldr/` (indefinitely, by default) and digests are written to the output folder
  (default `./audio-tldr-output/`). Anyone who can read those directories can read your content.
  Clearing them is yours to do — `--clear`, `--clear-all`, or `--set-retention`.
- **The digest phase sends transcript text to a model** — your own Claude session, or your own
  Ollama server if you set `digest_model: ollama:<model>`. The audio itself never leaves the
  machine. Neither does the transcript, on the Ollama path.

## What we DO treat as vulnerabilities

- **Command or argument injection** into the `yt-dlp`, `ffmpeg`, or whisper invocations, from a
  URL, media title, filename, preferences file, or transcript. Every call passes an argument list;
  none goes through a shell, and a report that breaks that is a real finding.
- **Path escape** — a source title or episode metadata that writes outside the cache and output
  directories. Titles are reduced to alphanumerics, spaces, `-`, and `_` before use as a filename.
- **Files landing where the docs don't say**, or with permissions wider than your own user.
- **Content reaching a network destination other than the ones above** — a transcript leaving the
  machine when the fully-local pipeline was configured, or any telemetry at all.
- **Secrets from your environment** appearing in a digest, a log line, or an output file.

Thanks for helping keep audio-tldr users safe.
