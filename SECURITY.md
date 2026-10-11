# Security Policy

## Supported versions

Security fixes land on the latest `1.x` release and `main`; older builds are not separately
patched — please update to the latest release.

| Version       | Supported          |
|---------------|--------------------|
| latest `0.9.x`| ✅                  |
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
  summarization, not a defect we can patch away. Section notes produced while digesting a long
  transcript in parts are treated as untrusted content too.
- **Transcripts and digests persist in cleartext.** Transcripts are cached under
  `~/.cache/audio-tldr/` (indefinitely, by default) and digests are written to the output folder
  (default `./audio-tldr-output/`). Anyone who can read those directories can read your content.
  Clearing them is yours to do — `--clear`, `--clear-all`, or `--set-retention`.
- **The digest phase sends transcript text to a model** — your own Claude session, or your own
  Ollama server if you set `digest_model: ollama:<model>`. The audio itself never leaves the
  machine. Neither does the transcript, on the Ollama path.

- **Transcript correction treats the model's edit list as untrusted data.** Before each digest a
  model proposes edits to the transcript; `correct.py` accepts an edit only if it replaces at
  most 24 characters with text that sounds similar (checked with `pypinyin` / `jellyfish`),
  lands in one unambiguous place (a `scope=all` edit may land in up to 20 places; a `scope=once` edit whose `wrong` text occurs only once is accepted even if its surrounding context differs), replaces a number character (digit or Chinese numeral) only with a character of identical reading, tones ignored, adds no symbols or invisible characters and
  does not mix Chinese and Latin script. All edits together may change at most 5% of the text
  (or 24 characters, whichever is larger). The reply parser reads at most 1,000,000
  characters and tries at most 64 array start positions. The corrected copy is kept
  only if every accepted span is in bounds, the replaced text equals the `wrong` text, spans do
  not overlap, and rebuilding the original from exactly the accepted edits gives the corrected
  text; otherwise the whole copy is discarded. The original transcript is never written. What
  this cannot rule out: a replacement that sounds alike but means something else (for example
  Paris → Prague) passes the sound check, and the limits above only bound how much of that can
  happen. Corrected copies and `corrections.json` are plaintext in the cache folder.

## What we DO treat as vulnerabilities

- **Command or argument injection** into the `yt-dlp`, `ffmpeg`, or whisper invocations, from a
  URL, media title, filename, preferences file, or transcript. Every call passes an argument list;
  none goes through a shell, and a report that breaks that is a real finding.
- **Path escape** — a source title or episode metadata that writes outside the cache and output
  directories. Titles are reduced to alphanumerics, spaces, `-`, and `_` before use as a filename.
- **Files landing where the docs don't say**, or with permissions wider than your own user.
- **Content reaching a network destination other than the ones above** — a transcript leaving the
  machine when the fully-local pipeline was configured, or any telemetry at all.
- **A correction outside those limits being applied**, or the corrected copy changing the
  original transcript file.
- **Secrets from your environment** appearing in a digest, a log line, or an output file.

Thanks for helping keep audio-tldr users safe.
