"""Offline tests for scripts/phonetic.py. The real pypinyin and jellyfish are
used for verdicts (CI installs both); availability is tested with fake modules."""
import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).parent.parent / "skills" / "audio-tldr" / "scripts" / "phonetic.py"
spec = importlib.util.spec_from_file_location("phonetic", SCRIPT)
ph = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ph)


def test_script_of():
    assert ph.script_of("正吉坐墊") == "zh"
    assert ph.script_of("Ray Chan") == "en"
    assert ph.script_of("Germany 傑米尼") == "mixed"
    assert ph.script_of("52%") == "none"


def test_zh_same_sound_passes():
    assert ph.sound_check("正吉", "正脊").ok
    assert ph.sound_check("練才", "斂財").ok
    assert ph.sound_check("一桌上去", "一坐上去").ok  # zh/z fuzzy


def test_zh_one_of_three_syllables_may_differ():
    assert ph.sound_check("盛夢公", "謝孟恭").ok


def test_zh_half_of_syllables_different_is_blocked():
    v = ph.sound_check("中國", "中共")
    assert not v.ok and v.reason == "sound"


def test_zh_syllable_count_must_match():
    v = ph.sound_check("電子", "墊子加厚")
    assert not v.ok and v.reason == "syllable_count"


def test_zh_digits_read_digit_by_digit_or_as_number():
    assert ph.sound_check("無二折", "52折").ok   # 五二
    assert ph.sound_check("四十幾歲", "40幾歲").ok  # 四十


def test_zh_heteronym_takes_closest_reading():
    assert ph.sound_check("長大", "漲大").ok  # 長 zhang/chang


def test_en_metaphone():
    assert ph.sound_check("RayChain", "Roichen").ok
    assert ph.sound_check("Ray Chan", "Roichen").ok
    assert ph.sound_check("Brockham", "Broadcom").ok
    assert not ph.sound_check("Apple", "Google").ok
    assert not ph.sound_check("Nvidia", "AMD").ok


def test_en_fullwidth_equals_halfwidth():
    assert ph.sound_check("Ｇｅｍｉｎｉ", "Gemini").distance == 0


def test_mixed_script_is_rejected():
    v = ph.sound_check("Germany", "傑米尼")
    assert not v.ok and v.reason == "mixed_script"


def test_missing_checker_rejects(monkeypatch):
    monkeypatch.setattr(ph, "available", lambda: {"zh": False, "en": True})
    v = ph.sound_check("正吉", "正脊")
    assert not v.ok and v.reason == "checker_unavailable"
    assert ph.sound_check("Marvel", "Marvell").ok


def test_available_reports_missing_module(monkeypatch):
    import builtins
    real = builtins.__import__

    def fake(name, *a, **k):
        if name == "jellyfish":
            raise ImportError("no jellyfish")
        return real(name, *a, **k)
    monkeypatch.setattr(builtins, "__import__", fake)
    try:
        ph._AVAILABLE.clear()
        assert ph.available() == {"zh": True, "en": False}
    finally:
        ph._AVAILABLE.clear()


def test_changed_numbers_are_rejected():
    for a, b in [("Gemini 2", "Gemini 3"), ("GPT-4", "GPT-5"), ("Q3", "Q4"),
                 ("Apple", "Apple 5"), ("第2名", "第3名")]:
        v = ph.sound_check(a, b)
        assert not v.ok and v.reason == "number_changed", (a, b, v)


def test_one_sided_digits_still_read():
    assert ph.sound_check("無二折", "52折").ok
    assert ph.sound_check("四十幾歲", "40幾歲").ok


def test_zh_numeral_changes_are_rejected_even_inside_the_budget():
    for a, b in [("第3名", "第五名"), ("第三名", "第五名")]:
        v = ph.sound_check(a, b)
        assert not v.ok and v.reason == "number_changed", (a, b, v)
    assert ph.sound_check("盛夢公", "謝孟恭").ok


def test_number_characters_are_compared_without_fuzzy_folding():
    for a, b in [("第十名", "第四名"), ("十四", "四十"), ("十四號", "四十號"),
                 ("這是個", "這四個"), ("3", "山")]:
        v = ph.sound_check(a, b)
        assert not v.ok and v.reason == "number_changed", (a, b, v)
    assert ph.sound_check("無二折", "52折").ok
    assert ph.sound_check("四十幾歲", "40幾歲").ok
    assert ph.sound_check("盛夢公", "謝孟恭").ok


def test_empty_english_keys_do_not_pass():
    assert ph._en_key("Y") == "" and ph._en_key("W") == ""  # jellyfish: no key
    v = ph.sound_check("Y", "W")
    assert not v.ok and v.reason == "sound"


def test_fullwidth_digits_are_not_a_number_change():
    v = ph.sound_check("52折", "５２折")
    assert v.reason != "number_changed"
    assert v.ok


FIXTURE = Path(__file__).parent / "fixtures" / "correct" / "sound_pairs.tsv"


def _pairs():
    for line in FIXTURE.read_text(encoding="utf-8").splitlines():
        if line.strip() and not line.startswith("#"):
            lang, expect, wrong, right, source = line.split("\t")
            yield lang, expect, wrong, right, source


def test_calibration_set_is_big_enough():
    from collections import Counter
    n = Counter()
    for lang, expect, w, r, _ in _pairs():
        if expect == "block" and ph.sound_check(w, r).reason not in ("sound", "syllable_count"):
            continue  # number_changed rows never reach the sound threshold
        n[(lang, expect)] += 1
    assert {e for _, e, *_ in _pairs()} <= {"pass", "block", "limit"}
    for key in (("zh", "pass"), ("zh", "block"), ("en", "pass"), ("en", "block")):
        assert n[key] >= 50, key


CONTROL_ROWS = {
    ("zh", "pass", "正吉", "正脊"), ("zh", "pass", "練才", "斂財"), ("zh", "pass", "盛夢公", "謝孟恭"),
    ("zh", "pass", "無二折", "52折"), ("zh", "pass", "空腹員", "空服員"), ("zh", "pass", "馬達松", "馬拉松"),
    ("zh", "pass", "剛大灣", "剛搭完"), ("zh", "pass", "阿聯球", "阿聯酋"),
    ("zh", "block", "中國", "中共"), ("zh", "block", "蘋果", "谷歌"), ("zh", "block", "台北", "高雄"),
    ("en", "pass", "RayChain", "Roichen"), ("en", "pass", "Ray Chan", "Roichen"),
    ("en", "pass", "Germany", "Gemini"), ("en", "pass", "Germini", "Gemini"),
    ("en", "pass", "Brockham", "Broadcom"), ("en", "pass", "Marvel", "Marvell"),
    ("en", "pass", "Samtech", "Semtech"), ("en", "pass", "Lumetan", "Lumentum"),
    ("en", "pass", "Cohelon", "Coherent"), ("en", "pass", "Max Linear", "MaxLinear"),
    ("en", "pass", "openway", "open weight"), ("en", "pass", "Halapeno", "Jalapeno"),
    ("en", "block", "Apple", "Google"), ("en", "block", "Nvidia", "AMD"), ("en", "block", "Tesla", "Toyota"),
    ("en", "block", "Meta", "Microsoft"), ("en", "block", "Intel", "Qualcomm"),
    ("en", "block", "Germany", "France"), ("en", "block", "Broadcom", "Marvell"),
    ("en", "block", "Samsung", "Sony"),
}


def test_control_rows_are_still_present():
    have = {(lang, e, w, r) for lang, e, w, r, _ in _pairs()}
    assert CONTROL_ROWS <= have, CONTROL_ROWS - have


def test_thresholds_are_pinned_by_boundary_rows():
    """Rows near the threshold are what make a moved constant fail the calibration."""
    band = {"zh": [0, 0], "en": [0, 0]}
    limit = {"zh": ph.ZH_MAX_MISMATCH, "en": ph.EN_MAX_DISTANCE}
    for lang, e, w, r, _ in _pairs():
        v = ph.sound_check(w, r)
        if e == "pass" and v.distance and 0 < v.distance <= limit[lang] + 1e-9:
            band[lang][0] += 1
        if (e == "block" and v.reason == "sound" and v.distance is not None
                and limit[lang] <= v.distance <= limit[lang] + 0.35):
            band[lang][1] += 1
    for lang, (n_pass, n_block) in band.items():
        assert n_pass >= 10 and n_block >= 10, (lang, n_pass, n_block)


def test_calibration_pairs():
    wrong_verdicts = [(w, r, e) for lang, e, w, r, _ in _pairs()
                      if e != "limit" and ph.sound_check(w, r).ok != (e == "pass")]
    assert not wrong_verdicts, wrong_verdicts


def test_known_limits_are_listed():
    """`limit` rows: metaphone hears them as alike though they differ in meaning."""
    limits = [(w, r) for _, e, w, r, _ in _pairs() if e == "limit"]
    assert len(limits) <= 5, limits
    assert all(ph.sound_check(w, r).ok for w, r in limits), limits


def test_en_compares_word_by_word():
    v = ph.sound_check("Bull market", "Bear market")
    assert not v.ok and v.reason == "sound"
    assert ph.sound_check("Max Linear", "Max Linear").ok
    assert ph.sound_check("Samtech chips", "Semtech chips").ok
    assert not ph.sound_check("Samtech chips", "Semtech cars").ok
