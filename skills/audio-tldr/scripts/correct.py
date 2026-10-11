#!/usr/bin/env python3
"""Apply an LLM's proposed corrections to a transcript, safely.

The edit list is untrusted. Each edit may only swap a short span for something
that sounds alike (phonetic.py), must be located unambiguously by its context,
must not overlap another, and the total change is capped. The assembled copy
is then verified independently: every accepted span is checked against the
original (in bounds, equal to `wrong`, no overlap) and the text is rebuilt
from exactly the accepted records; any mismatch discards the whole copy. The original transcript is never written."""
import argparse
import hashlib
import importlib.util
import json
import os
import re
import sys
import unicodedata
from collections import Counter, namedtuple
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import phonetic  # noqa: E402

MAX_SPAN = 24
MAX_EDITS = 500
MAX_ALL_COUNT = 20
SHOW_COUNT = 5
MAX_CHANGE_RATIO = 0.05
MIN_CHANGE_CHARS = 24

Result = namedtuple("Result", "text accepted rejected")


class EditsError(ValueError):
    pass


MAX_PARSE_CHARS = 1_000_000
MAX_PARSE_STARTS = 64
_FENCE = re.compile(r"```[A-Za-z]*[ \t]*\r?\n(.*?)```", re.S)


def _try_array(raw, start, dec):
    try:
        data, _ = dec.raw_decode(raw, start)
    except (ValueError, RecursionError):
        return None
    return data if isinstance(data, list) else None


def parse_edits(raw):
    """First complete JSON array in the reply (models wrap it in fences or chatter).
    Work is bounded: input size cap, fenced blocks first, then at most
    MAX_PARSE_STARTS bracket positions."""
    if len(raw) > MAX_PARSE_CHARS:
        raise EditsError("reply too large")
    dec = json.JSONDecoder()
    for m in _FENCE.finditer(raw):
        body = m.group(1)
        i = body.find("[")
        if i != -1:
            data = _try_array(body, i, dec)
            if data is not None:
                return data
    start = raw.find("[")
    for _ in range(MAX_PARSE_STARTS):
        if start == -1:
            break
        data = _try_array(raw, start, dec)
        if data is not None:
            return data
        start = raw.find("[", start + 1)
    raise EditsError("no JSON array of edits found")


FIELDS = ("wrong", "right", "before", "after", "scope")


def _rec(e, **extra):
    """Whitelisted copy of an edit for the result records."""
    out = {k: e[k] for k in FIELDS if isinstance(e, dict) and k in e}
    for k in ("before", "after"):
        if isinstance(out.get(k), str):
            out[k] = out[k][:64]
    if isinstance(e, dict) and isinstance(e.get("why"), str):
        out["why"] = e["why"][:200]
    out.update(extra)
    return out


def _well_formed(e):
    return (isinstance(e, dict) and isinstance(e.get("wrong"), str) and e["wrong"].strip() != ""
            and all(isinstance(e.get(k), str) for k in ("wrong", "right"))
            and e.get("scope", "once") in ("once", "all")
            and all(isinstance(e.get(k, ""), str) for k in ("before", "after")))


def _occurrences(text, wrong):
    if phonetic.script_of(wrong) == "en":
        pat = r"(?<![A-Za-z])" + re.escape(wrong) + r"(?![A-Za-z])"
    else:
        pat = re.escape(wrong)
    return [m.start() for m in re.finditer(pat, text)]


def _locate(text, e):
    hits = _occurrences(text, e["wrong"])
    if not hits:
        return None, "not_found"
    if e.get("scope") == "all":
        return hits, None
    before, after, w = e.get("before", ""), e.get("after", ""), e["wrong"]
    ctx = [h for h in hits if text[max(0, h - len(before)):h] == before
           and text[h + len(w):h + len(w) + len(after)] == after]
    if len(ctx) == 1:
        return ctx, None
    if len(hits) == 1:
        return hits, None
    return None, "ambiguous"


def _is_sound_char(c):
    return unicodedata.category(c)[0] in "LNZ" or c.isspace()


def _added_symbols(wrong, right):
    """Characters that are not letters, numbers or spaces may be dropped but not added."""
    nw = Counter(c for c in unicodedata.normalize("NFKC", wrong) if not _is_sound_char(c))
    nr = Counter(c for c in unicodedata.normalize("NFKC", right) if not _is_sound_char(c))
    return bool(nr - nw)


def _has_invisible(text):
    return any(unicodedata.category(c) in ("Cc", "Cf", "Zl", "Zp") for c in text)


def _too_short_for_all(wrong):
    zh = sum(1 for c in wrong if "㐀" <= c <= "鿿")
    letters = sum(1 for c in wrong if c.isalpha() and c.isascii())
    return zh < 2 and letters < 4


def _assemble(text, spans):
    out, pos = [], 0
    for s, e, right in sorted(spans):
        out.append(text[pos:s])
        out.append(right)
        pos = e
    out.append(text[pos:])
    return "".join(out)


def verify(original, corrected, accepted):
    """Independent of `_assemble`: it rebuilds the text from the accepted records
    (not from the `taken` tuples the assembler used) after checking every span
    against the original: in bounds, `original[s:e] == wrong`, no two overlap.
    The rebuild must equal `corrected` exactly, so nothing else can differ."""
    allowed = {}
    for a in accepted:
        for s, e in a["spans"]:
            if not (0 <= s < e <= len(original)) or original[s:e] != a["wrong"]:
                return False
            if (s, e) in allowed:
                return False
            allowed[(s, e)] = a["right"]
    ordered = sorted(allowed)
    for (s1, e1), (s2, e2) in zip(ordered, ordered[1:]):
        if s2 < e1:
            return False
    rebuilt, pos = [], 0
    for (s, e) in ordered:
        rebuilt.append(original[pos:s])
        rebuilt.append(allowed[(s, e)])
        pos = e
    rebuilt.append(original[pos:])
    return "".join(rebuilt) == corrected


def _size(a):
    return max(len(a["wrong"]), len(a["right"])) * a["count"]


def apply_edits(text, edits, check=None):
    check = check or phonetic.sound_check
    accepted, rejected, taken = [], [], []
    for n, e in enumerate(edits):
        if n >= MAX_EDITS:
            rejected.append({"edit": repr(e)[:200], "reason": "too_many_edits"})
            continue
        if not _well_formed(e):
            rejected.append({"edit": repr(e)[:200], "reason": "malformed"})
            continue
        w, r = e["wrong"], e["right"]
        if w == r:
            rejected.append({**_rec(e), "reason": "no_change"})
            continue
        if len(w) > MAX_SPAN or len(r) > MAX_SPAN or "\n" in w + r or "\r" in w + r:
            rejected.append({**_rec(e), "reason": "too_long"})
            continue
        if e.get("scope") == "all" and _too_short_for_all(w):
            rejected.append({**_rec(e), "reason": "too_short_for_all"})
            continue
        if _has_invisible(r):
            rejected.append({**_rec(e), "reason": "malformed"})
            continue
        if _added_symbols(w, r):
            rejected.append({**_rec(e), "reason": "added_symbols"})
            continue
        v = check(w, r)
        if not v.ok:
            rejected.append({**_rec(e), "reason": v.reason, "distance": v.distance})
            continue
        starts, why = _locate(text, e)
        if why:
            rejected.append({**_rec(e), "reason": why})
            continue
        if len(starts) > MAX_ALL_COUNT:
            rejected.append({**_rec(e), "reason": "too_many_occurrences"})
            continue
        spans = [(s, s + len(w)) for s in starts]
        if any(s < te and ts < en for s, en in spans for ts, te, _ in taken):
            rejected.append({**_rec(e), "reason": "overlap"})
            continue
        taken += [(s, en, r) for s, en in spans]
        accepted.append({**_rec(e), "distance": v.distance, "count": len(spans),
                         "spans": [list(sp) for sp in spans]})

    cap = max(int(len(text) * MAX_CHANGE_RATIO), MIN_CHANGE_CHARS)
    while accepted and sum(_size(a) for a in accepted) > cap:
        worst = max(accepted, key=lambda a: (a["distance"] or 0, _size(a)))
        accepted.remove(worst)
        taken = [t for t in taken if [t[0], t[1]] not in worst["spans"]]
        rejected.append({**_rec(worst), "reason": "total_change_cap"})

    corrected = _assemble(text, taken)
    if not verify(text, corrected, accepted):
        failed = [{**_rec(a), "reason": "verify_failed"} for a in accepted]
        return Result(text, [], failed + rejected)
    return Result(corrected, accepted, rejected)


CORRECTION_VERSION = 1
_HERE = Path(__file__).resolve().parent


def _load(name):
    spec = importlib.util.spec_from_file_location(f"_atl_{name}", _HERE / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


transcribe = _load("transcribe")
digest = _load("digest")


def _sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def reference_key(glossary, context):
    ctx = context or {}
    canon = {"glossary": sorted([t, sorted(v)] for t, v in glossary),
             "context": {k: ctx.get(k) for k in ("title", "channel", "creator", "tags", "chapters", "description")}}
    return _sha(json.dumps(canon, ensure_ascii=False, sort_keys=True))


def input_key(transcript_text, ref_key):
    return {"transcript_sha256": _sha(transcript_text), "reference_key": ref_key,
            "correction_version": CORRECTION_VERSION}


def _existing(entry, name):
    p = transcribe.derived_file(entry, name)
    return p if p.is_file() else None


def _read_corrections(entry):
    p = _existing(entry, "corrections")
    if p is None:
        return None
    try:
        return json.loads(transcribe._read_text(p))
    except (OSError, ValueError):
        return None


def load_corrected(entry, key, text):
    c = _read_corrections(entry)
    path = _existing(entry, "corrected")
    if not isinstance(c, dict) or path is None:
        return None
    k = c.get("key")
    if not isinstance(k, dict):
        return None
    ver = k.get("correction_version")
    if not isinstance(ver, int) or isinstance(ver, bool) or ver < CORRECTION_VERSION:
        return None
    try:
        sha_ok = c.get("corrected_sha256") == _sha(transcribe._read_text(path))
    except OSError:
        return None
    if not sha_ok:
        return None
    if ver > CORRECTION_VERSION:
        return path  # written by a newer install: its key scheme is not ours to judge
    if k.get("transcript_sha256") != key["transcript_sha256"] or k.get("reference_key") != key["reference_key"]:
        return None
    # installing a checker that was missing at apply time earns one recompute
    recorded = c.get("checkers")
    recorded = recorded if isinstance(recorded, dict) else {}
    now = phonetic.available()
    for script in _needed_checkers(text):
        if not recorded.get(script) and now.get(script):
            return None
    return path


SUPPORTED_LANGUAGES = {"zh", "yue", "en"}
# whisper.cpp and openai-whisper store what the user passed: a region tag (zh-TW) or a name.
LANGUAGE_NAMES = {"chinese": "zh", "mandarin": "zh", "cantonese": "yue", "english": "en"}


def _language_code(lang):
    lang = lang.strip().lower()
    return LANGUAGE_NAMES.get(lang) or re.split(r"[-_]", lang, maxsplit=1)[0]


def _unsupported_language(entry):
    """True when meta.json names a language the checkers do not cover (Japanese kanji
    would be read with Mandarin sounds). Missing or unreadable meta: not decided here."""
    try:
        meta = json.loads(transcribe._read_text(Path(entry) / "meta.json"))
    except (OSError, ValueError):
        return False
    lang = meta.get("language") if isinstance(meta, dict) else None
    return isinstance(lang, str) and lang.strip() != "" and _language_code(lang) not in SUPPORTED_LANGUAGES


def _inputs(entry, context_arg):
    t = transcribe.resolve_entry_file(entry, "transcript")
    if t is None:
        return None
    text = transcribe._read_text(t)
    glossary = digest.load_glossary()
    context_arg = context_arg or transcribe.context_path_for(entry)
    context = digest.load_context(context_arg) if context_arg else None
    return text, glossary, context, input_key(text, reference_key(glossary, context))


def _needed_checkers(text):
    """Which checkers this transcript needs: zh when it has Chinese, en when it has
    Latin words. Only those count when deciding whether a subagent is worth it."""
    need = set()
    if any("\u3400" <= c <= "\u9fff" for c in text):
        need.add("zh")
    if re.search(r"[A-Za-z]{2,}", text):
        need.add("en")
    return need


def cmd_check(args):
    entry = Path(args.entry)
    inputs = _inputs(entry, args.context)
    if inputs is None:
        print(json.dumps({"status": "skip", "reason": "no_transcript"}))
        return 0
    if _unsupported_language(entry):
        print(json.dumps({"status": "skip", "reason": "unsupported_language"}))
        return 0
    text, glossary, context, key = inputs
    hit = load_corrected(entry, key, text)
    if hit:
        print(json.dumps({"status": "cached", "corrected_path": str(hit)}))
        return 0
    avail = phonetic.available()
    need = _needed_checkers(text)
    if not need:
        print(json.dumps({"status": "skip", "reason": "nothing_to_check"}))
        return 0
    if not any(avail[k] for k in need):
        print(json.dumps({"status": "skip", "reason": "checker_unavailable"}))
        return 0
    ref = digest.build_reference(context, glossary)
    ref_path = transcribe.derived_file(entry, "reference")
    transcribe._atomic_write_text(ref_path, ref or "# Reference for name spellings\n\n(none)\n")
    print(json.dumps({"status": "pending", "reference_path": str(ref_path),
                      "transcript_path": str(transcribe.resolve_entry_file(entry, "transcript"))}))
    return 0


def cmd_apply(args):
    entry = Path(args.entry)
    inputs = _inputs(entry, args.context)
    if inputs is None:
        print(json.dumps({"corrected_path": None, "reason": "no_transcript"}))
        return 0
    if _unsupported_language(entry):
        print(json.dumps({"corrected_path": None, "reason": "unsupported_language"}))
        return 0
    text, glossary, context, key = inputs
    try:
        raw = sys.stdin.read() if args.edits == "-" else transcribe._read_text(Path(args.edits))
    except (OSError, UnicodeDecodeError):
        print(json.dumps({"corrected_path": None, "reason": "edits_unreadable"}))
        return 0
    try:
        edits = parse_edits(raw)
    except EditsError:
        print(json.dumps({"corrected_path": None, "reason": "no_edit_list"}))
        return 0
    return _apply_and_store(entry, text, key, edits, args.model)


def _checker_script(rec):
    """Which checker a rejected edit needed: the script of `wrong`, else of `right`
    (as phonetic.sound_check picks it); mixed counts as zh, anything else en."""
    sc = phonetic.script_of(rec.get("wrong", ""))
    if sc == "none":
        sc = phonetic.script_of(rec.get("right", ""))
    return "zh" if sc in ("zh", "mixed") else "en"


def _apply_and_store(entry, text, key, edits, model, extra=None):
    existing = _read_corrections(entry)
    ekey = existing.get("key") if isinstance(existing, dict) else None
    if isinstance(ekey, dict) and isinstance(ekey.get("correction_version"), int) \
            and ekey["correction_version"] > CORRECTION_VERSION:
        hit = _existing(entry, "corrected")
        print(json.dumps({"corrected_path": str(hit) if hit else None, "reason": "newer_version_kept"}))
        return 0
    res = apply_edits(text, edits)
    unavailable = sorted({_checker_script(r) for r in res.rejected if r.get("reason") == "checker_unavailable"})
    shown = [{"wrong": a["wrong"], "right": a["right"], "count": a["count"]}
             for a in res.accepted if a["count"] >= SHOW_COUNT]
    out_path = transcribe.derived_file(entry, "corrected")
    # newline="": the text came from a bytes read, so on Windows it already has the
    # transcript's \r\n; text mode would make them \r\r\n and break the hash check
    transcribe._atomic_write_text(out_path, res.text, newline="")
    record = {"key": key, "model": model, "date": datetime.now(timezone.utc).isoformat(),
              "corrected_sha256": _sha(res.text),
              "checkers": phonetic.available(),
              "thresholds": {"zh_max_mismatch": phonetic.ZH_MAX_MISMATCH,
                             "en_max_distance": phonetic.EN_MAX_DISTANCE},
              "packages": _package_versions(),
              "accepted": res.accepted, "rejected": res.rejected, **(extra or {})}
    transcribe._atomic_write_text(transcribe.derived_file(entry, "corrections"),
                                  json.dumps(record, ensure_ascii=False, indent=1))
    print(json.dumps({"corrected_path": str(out_path),
                      "accepted": len(res.accepted), "rejected": len(res.rejected), "shown": shown,
                      "corrections_path": str(transcribe.derived_file(entry, "corrections")),
                      **({"unavailable": unavailable} if unavailable else {}), **(extra or {})},
                     ensure_ascii=False))
    return 0


def _package_versions():
    """Installed distribution versions; jellyfish 1.x has no __version__."""
    from importlib import metadata
    out = {}
    for mod in CHECKER_MODULES:
        if importlib.util.find_spec(mod) is None:
            out[mod] = None
            continue
        try:
            out[mod] = metadata.version(mod)
        except metadata.PackageNotFoundError:
            out[mod] = getattr(__import__(mod), "__version__", "unknown")
    return out


def _context_fits(line, h, a):
    """before/after are cut at the line edges, so compare only the part that fits."""
    w, bf, af = a["wrong"], a.get("before", ""), a.get("after", "")
    left = line[max(0, h - len(bf)):h]
    right = line[h + len(w):h + len(w) + len(af)]
    return bf.endswith(left) and af.startswith(right)


_VTT_BLOCK = re.compile(r"(?:WEBVTT|NOTE|STYLE)(?:[ \t\r]|$)")


def _core(line):
    """A line without its trailing CR, so CRLF files match like LF ones."""
    return line[:-1] if line.endswith("\r") else line


def _text_lines(blocks):
    """(block, line) positions that are caption text: only lines after a cue's
    timing line. Header/NOTE/STYLE blocks and blocks without timing are skipped."""
    out = []
    for k, lines in enumerate(blocks):
        if not lines or _VTT_BLOCK.match(lines[0]):
            continue
        t = next((i for i, l in enumerate(lines) if "-->" in l), None)
        if t is None:
            continue
        out += [(k, i) for i in range(t + 1, len(lines))]
    return out


def apply_to_subtitle(sub_text, accepted):
    """Place accepted edits inside single cue text lines, all against the ORIGINAL
    text (an edit overlapping an earlier placement is skipped), then splice once.
    An edit that only matches across a cue boundary is skipped."""
    parts = re.split(r"(\r?\n\r?\n)", sub_text)
    blocks = [p.split("\n") for p in parts]
    keys = _text_lines(blocks)
    placed = {}  # (k, i) -> [(start, end, right)]
    applied = skipped = 0

    def free(key, h, w):
        return all(h + w <= s0 or h >= e0 for s0, e0, _ in placed.get(key, []))

    for a in accepted:
        if not (isinstance(a, dict) and isinstance(a.get("wrong"), str) and a["wrong"]
                and isinstance(a.get("right"), str)):
            skipped += 1
            continue
        w = len(a["wrong"])
        cands = [(key, h) for key in keys for h in _occurrences(_core(blocks[key[0]][key[1]]), a["wrong"])]
        if a.get("scope") == "all":
            chosen = cands
        else:
            ctx = [c for c in cands if _context_fits(_core(blocks[c[0][0]][c[0][1]]), c[1], a)]
            chosen = ctx if len(ctx) == 1 else cands if len(cands) == 1 else []
        chosen = [(key, h) for key, h in chosen if free(key, h, w)]
        for key, h in chosen:
            placed.setdefault(key, []).append((h, h + w, a["right"]))
        applied += bool(chosen)
        skipped += not chosen
    for (k, i), spans in placed.items():
        raw = blocks[k][i]
        line, out, pos = _core(raw), "", 0
        for s0, e0, right in sorted(spans):
            out += line[pos:s0] + right
            pos = e0
        blocks[k][i] = out + line[pos:] + raw[len(line):]
    return "".join("\n".join(b) for b in blocks), applied, skipped


def cmd_subtitle(args):
    entry = Path(args.entry)
    try:
        meta = json.loads(transcribe._read_text(entry / "meta.json"))
    except (OSError, ValueError):
        meta = None
    if not isinstance(meta, dict):
        print(json.dumps({"subtitle_path": None, "reason": "no_meta"}))
        return 0
    path, err = transcribe._ensure_subtitle(entry, meta, args.format)
    if err:
        print(json.dumps({"subtitle_path": None, "error": err}, ensure_ascii=False))
        return 2
    c = _read_corrections(entry)
    accepted = c.get("accepted") if isinstance(c, dict) else None
    if not accepted or not isinstance(accepted, list):
        print(json.dumps({"subtitle_path": path, "applied": 0, "skipped": 0}))
        return 0
    inputs = _inputs(entry, args.context)
    if inputs is None or load_corrected(entry, inputs[3], inputs[0]) is None:
        print(json.dumps({"subtitle_path": path, "applied": 0, "skipped": 0,
                          "reason": "no_valid_corrections"}))
        return 0
    text, applied, skipped = apply_to_subtitle(transcribe._read_text(Path(path)), accepted)
    out = transcribe.derived_file(entry, f"corrected_{args.format}")
    transcribe._atomic_write_text(out, text, newline="")  # keep the subtitle's own line endings
    print(json.dumps({"subtitle_path": str(out), "applied": applied, "skipped": skipped}))
    return 0


PROMPT_PATH = _HERE.parent / "prompts" / "correct.md"


def _edit_sig(e):
    """Dedup key across chunks: `why` and extra fields never count; a scope=all
    edit is the same edit wherever its context was seen."""
    if not isinstance(e, dict):
        return json.dumps(e, sort_keys=True, ensure_ascii=False, default=repr)
    if e.get("scope") == "all":
        k = ("all", e.get("wrong"), e.get("right"))
    else:
        k = ("once", e.get("wrong"), e.get("right"), e.get("before", ""), e.get("after", ""))
    return json.dumps(k, ensure_ascii=False, default=repr)


def chunks(text, size=6000):
    return [c.text for c in digest.split_lines(text, size, overlap_lines=1)]


def cmd_ollama(args):
    entry = Path(args.entry)
    inputs = _inputs(entry, args.context)
    if inputs is None:
        print(json.dumps({"corrected_path": None, "reason": "no_transcript"}))
        return 0
    if _unsupported_language(entry):
        print(json.dumps({"corrected_path": None, "reason": "unsupported_language"}))
        return 0
    text, glossary, context, key = inputs
    hit = load_corrected(entry, key, text)
    if hit:
        print(json.dumps({"corrected_path": str(hit), "accepted": None, "rejected": None,
                          "shown": [], "cached": True}))
        return 0
    instructions = PROMPT_PATH.read_text(encoding="utf-8")
    reference = digest.build_reference(context, glossary)
    host = digest.resolve_ollama_host(args.ollama_host)
    merged, seen = [], set()
    parts = chunks(text)
    unparsed = 0
    usage = {}
    try:
        for part in parts:
            reply = digest.call_ollama_chat(host, args.model,
                                            digest.build_messages(instructions, part, reference),
                                            truncate=False, options={"num_ctx": digest.ollama_num_ctx(host, args.model)},
                                            usage=usage)
            try:
                for e in parse_edits(reply):
                    sig = _edit_sig(e)
                    if sig not in seen:
                        seen.add(sig)
                        merged.append(e)
            except EditsError:
                unparsed += 1
    except (digest.OllamaUnreachable, digest.OllamaModelMissing, digest.OllamaError) as e:
        print(str(e), file=sys.stderr)
        return 2
    if usage:
        transcribe.append_usage(entry, {"phase": "correct", "path": "ollama", "model": args.model,
                                        "provider": "ollama", **usage})
    if parts and unparsed == len(parts):
        print(json.dumps({"corrected_path": None, "reason": "no_edit_list"}))
        return 0
    extra = {"chunks_unparsed": unparsed, "chunks": len(parts)} if unparsed else None
    return _apply_and_store(entry, text, key, merged, f"ollama:{args.model}", extra)


def cmd_usage(args):
    try:
        data = json.loads(args.json)
    except ValueError:
        data = None
    if not isinstance(data, dict):
        print("usage --json must be a JSON object", file=sys.stderr)
        return 2
    transcribe.append_usage(Path(args.entry), data)
    return 0


# --- CLI ---  (later tasks insert new functions ABOVE this line)


def _honor_explicit_python(raw_argv):
    """Same rule as transcribe.py: AUDIO_TLDR_PYTHON set -> run under it, so the
    optional checkers are looked up in the interpreter the user chose."""
    env_py = os.environ.get("AUDIO_TLDR_PYTHON")
    if not env_py or os.environ.get("AUDIO_TLDR_REEXECED"):
        return
    if Path(env_py).exists() and os.path.realpath(env_py) != os.path.realpath(sys.executable):
        os.environ["AUDIO_TLDR_REEXECED"] = "1"
        transcribe._reexec_into(env_py, os.path.abspath(__file__), raw_argv)


CHECKER_MODULES = ("pypinyin", "jellyfish")


def _checkers_in(python) -> int:
    return sum(transcribe._modules_in(python, CHECKER_MODULES).values())


def _find_checker_python(raw_argv):
    """The checkers may sit in another interpreter: the README says to install them
    where the whisper backend is, and transcribe.py switches to that interpreter on
    its own. Switch to the candidate with the most checkers when it has more than
    this one. Same candidates and loop guard as transcribe.py."""
    if os.environ.get("AUDIO_TLDR_REEXECED") or (raw_argv[:1] == ["usage"]):
        return
    have = sum(phonetic.available().values())
    if have == len(CHECKER_MODULES):
        return
    cur = os.path.realpath(sys.executable)
    best, best_n = None, have
    for cand in transcribe._candidate_interpreters():
        if os.path.realpath(cand) == cur:
            continue
        n = _checkers_in(cand)
        if n > best_n:
            best, best_n = cand, n
    if best:
        os.environ["AUDIO_TLDR_REEXECED"] = "1"
        print(f"note: sound checkers found in {best}; switching interpreter "
              f"(set AUDIO_TLDR_PYTHON to override)", file=sys.stderr)
        transcribe._reexec_into(best, os.path.abspath(__file__), raw_argv)


def _entry(raw_argv):
    _honor_explicit_python(raw_argv)
    _find_checker_python(raw_argv)
    return main(raw_argv)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="correct.py")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check")
    c.add_argument("entry")
    c.add_argument("--context")
    a = sub.add_parser("apply")
    a.add_argument("entry")
    a.add_argument("--edits", required=True)
    a.add_argument("--model", required=True)
    a.add_argument("--context")
    s = sub.add_parser("subtitle")
    s.add_argument("entry")
    s.add_argument("--format", choices=["srt", "vtt"], required=True)
    s.add_argument("--context")
    o = sub.add_parser("ollama")
    o.add_argument("entry")
    o.add_argument("--model", required=True)
    o.add_argument("--context")
    o.add_argument("--ollama-host")
    u = sub.add_parser("usage")
    u.add_argument("entry")
    u.add_argument("--json", required=True)
    args = ap.parse_args(argv)
    return {"check": cmd_check, "apply": cmd_apply, "subtitle": cmd_subtitle, "ollama": cmd_ollama,
            "usage": cmd_usage}[args.cmd](args)


if __name__ == "__main__":
    transcribe.utf8_stdio()
    sys.exit(_entry(sys.argv[1:]))
