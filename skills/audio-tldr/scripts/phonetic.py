"""Does a proposed correction sound like what speech recognition heard?

Chinese is compared syllable by syllable (pypinyin, tones dropped, common
confusions folded); English word by word (jellyfish metaphone). Both packages
are optional, like opencc: without one, edits in that script are rejected.
A whole-string distance is not used for Chinese on purpose: it dilutes one
entirely different syllable into a small number (中國 -> 中共 scores 0.33)."""
import re
import unicodedata
from collections import namedtuple

ZH_MAX_MISMATCH = 1 / 3
EN_MAX_DISTANCE = 0.45
FUZZY = (("zh", "z"), ("ch", "c"), ("sh", "s"), ("ing", "in"), ("eng", "en"),
         ("ang", "an"), ("l", "n"))
DIGITS = "零一二三四五六七八九"

Verdict = namedtuple("Verdict", "ok reason distance")
_AVAILABLE = {}


def available():
    if not _AVAILABLE:
        for key, mod in (("zh", "pypinyin"), ("en", "jellyfish")):
            try:
                __import__(mod)
                _AVAILABLE[key] = True
            except ImportError:
                _AVAILABLE[key] = False
    return dict(_AVAILABLE)


def _is_cjk(c):
    return "㐀" <= c <= "鿿"


def _ascii(text):
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()


def script_of(text):
    zh = any(_is_cjk(c) for c in text)
    en = any(c.isalpha() for c in _ascii(text))
    return "mixed" if zh and en else "zh" if zh else "en" if en else "none"


def _number_reading(n):
    """Spoken form of a non-negative integer below 10000 (四十, 兩百五十 -> 二百五十)."""
    if n < 10:
        return DIGITS[n]
    out, units = "", (("千", 1000), ("百", 100), ("十", 10))
    for unit, size in units:
        q, n = divmod(n, size)
        if q:
            out += ("" if unit == "十" and q == 1 and not out else DIGITS[q]) + unit
        elif out and n:
            out += "零" if not out.endswith("零") else ""
    return out + (DIGITS[n] if n else "")


def _digit_variants(text):
    """Each run of ASCII digits read digit by digit, and as a number."""
    runs = list(re.finditer(r"[0-9]+", text))
    if not runs:
        return [text]
    per_digit = re.sub(r"[0-9]", lambda m: DIGITS[int(m.group())], text)
    as_number = re.sub(r"[0-9]+", lambda m: _number_reading(int(m.group()))
                       if int(m.group()) < 10000 else "".join(DIGITS[int(c)] for c in m.group()),
                       text)
    return list(dict.fromkeys([per_digit, as_number]))


def _fold(syllable):
    for a, b in FUZZY:
        syllable = syllable.replace(a, b)
    return syllable


def _exact_readings(char):
    from pypinyin import Style, pinyin
    return set(pinyin(char, style=Style.NORMAL, heteronym=True)[0])


def _readings(char):
    return {_fold(r) for r in _exact_readings(char)}


def _syllables(text):
    return [c for c in text if _is_cjk(c)]


NUMERALS = set("〇零一二兩三四五六七八九十百千萬億")


def _zh_check(wrong, right):
    best = None
    number_changed = False
    for w in _digit_variants(wrong):
        for r in _digit_variants(right):
            ws, rs = _syllables(w), _syllables(r)
            if len(ws) != len(rs) or not ws:
                continue
            # a number character may only become a character read exactly alike (tones
            # ignored, no fuzzy folding): 十 -> 四 must not pass as shi ~ si
            if any((a in NUMERALS or b in NUMERALS) and not (_exact_readings(a) & _exact_readings(b))
                   for a, b in zip(ws, rs)):
                number_changed = True
                continue
            miss = sum(1 for a, b in zip(ws, rs)
                       if not (a in NUMERALS or b in NUMERALS) and not (_readings(a) & _readings(b)))
            ratio = miss / len(ws)
            if best is None or ratio < best:
                best = ratio
    if best is None:
        return Verdict(False, "number_changed" if number_changed else "syllable_count", None)
    passed = best <= ZH_MAX_MISMATCH + 1e-9
    return Verdict(passed, "ok" if passed else "sound", round(best, 3))


def _en_words(text):
    return re.sub(r"[^a-z ]", " ", _ascii(text)).split()


def _word_key(word):
    import jellyfish
    return jellyfish.metaphone(word)


def _en_key(text):
    return "".join(_word_key(w) for w in _en_words(text))


def _distance(a, b):
    if not a and not b:
        return 0.0
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1] / max(len(a), len(b))


def _en_check(wrong, right):
    ww, rw = _en_words(wrong), _en_words(right)
    if ww and len(ww) == len(rw):  # word by word: a shared word must not hide a different one
        ds = [_distance(_word_key(a), _word_key(b)) for a, b in zip(ww, rw)]
        d = round(max(ds), 3)
        if not any(_word_key(a) or _word_key(b) for a, b in zip(ww, rw)):
            return Verdict(False, "sound", None)
        ok = d <= EN_MAX_DISTANCE
        return Verdict(ok, "ok" if ok else "sound", d)
    kw, kr = _en_key(wrong), _en_key(right)
    if not kw and not kr:
        return Verdict(False, "sound", None)
    d = round(_distance(kw, kr), 3)
    return Verdict(d <= EN_MAX_DISTANCE, "ok" if d <= EN_MAX_DISTANCE else "sound", d)


def sound_check(wrong, right):
    wrong, right = unicodedata.normalize("NFKC", wrong), unicodedata.normalize("NFKC", right)
    dw, dr = re.findall(r"[0-9]+", wrong), re.findall(r"[0-9]+", right)
    if dw and dr and dw != dr:
        return Verdict(False, "number_changed", None)
    sw, sr = script_of(wrong), script_of(right)
    # digits on one side read as Chinese (無二折 -> 52折)
    if sw == "zh" and sr == "none" or sr == "zh" and sw == "none":
        sw = sr = "zh"
    if "mixed" in (sw, sr) or {sw, sr} == {"zh", "en"}:
        return Verdict(False, "mixed_script", None)
    script = sw if sw != "none" else sr
    if script == "none":
        return Verdict(False, "sound", None)
    if not available()[script]:
        return Verdict(False, "checker_unavailable", None)
    if script == "en" and dw != dr:  # English keys drop digits: Apple -> Apple 5 would pass
        return Verdict(False, "number_changed", None)
    return _zh_check(wrong, right) if script == "zh" else _en_check(wrong, right)
