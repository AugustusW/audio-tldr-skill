---
name: key-summary
description: Key takeaways, a one-paragraph summary, and an optional timeline (the default digest).
---

Produce, in the user's language:

## Key takeaways
3–7 bullets, each a single self-contained insight (not chapter titles).

## Summary
One paragraph, 100–200 words, covering the arc of the content.

## Timeline
Include ONLY if all hold: the `timeline` preference is not `off`, duration > 20 minutes,
and the transcript has clear topic shifts. 4–8 entries. Omit otherwise.

If the transcript lines already start with a time (`[MM:SS] …`), those are real segment
boundaries: quote them as `[MM:SS] topic`, and never round or invent one. Otherwise write
`~MM:SS topic`, estimating positions proportionally from text position — the `~` is what
marks the number as a guess, so keep it.
To change these conditions, copy this file to `~/.config/audio-tldr/templates/` and edit it.
