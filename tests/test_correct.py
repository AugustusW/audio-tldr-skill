"""Offline tests for scripts/correct.py. The sound check is the real one
(phonetic.py) unless a test passes its own."""
import importlib.util
import json
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).parent.parent / "skills" / "audio-tldr" / "scripts"
sys.path.insert(0, str(SCRIPTS))
spec = importlib.util.spec_from_file_location("correct", SCRIPTS / "correct.py")
co = importlib.util.module_from_spec(spec)
spec.loader.exec_module(co)

TEXT = "歡迎收聽古埃,我是盛夢公,本集節目由Ray Chan正吉坐墊贊助。Ray Chan正吉坐墊很好坐。"


def E(wrong, right, before="", after="", scope="once"):
    return {"wrong": wrong, "right": right, "before": before, "after": after, "scope": scope}


def test_parse_edits_accepts_fences_and_chatter():
    raw = '這是修改：\n```json\n[{"wrong":"a","right":"b","before":"","after":"","scope":"once"}]\n```\n完成'
    assert co.parse_edits(raw)[0]["right"] == "b"


def test_parse_edits_rejects_non_array():
    with pytest.raises(co.EditsError):
        co.parse_edits('{"wrong": "a"}')


def test_once_and_all():
    r = co.apply_edits(TEXT, [E("古埃", "股癌", "收聽", ",我是"), E("正吉", "正脊", scope="all")])
    assert "股癌" in r.text and r.text.count("正脊") == 2 and "正吉" not in r.text
    assert {a["wrong"]: a["count"] for a in r.accepted} == {"古埃": 1, "正吉": 2}


def test_different_sound_is_rejected_and_text_unchanged():
    r = co.apply_edits(TEXT, [E("盛夢公", "王小明", "我是", ",本集")])
    assert r.text == TEXT and r.rejected[0]["reason"] == "sound"


def test_rewrite_is_rejected():
    long = "本集節目由Ray Chan正吉坐墊贊助"
    r = co.apply_edits(TEXT, [E(long, "本集節目由某某公司贊助")])
    assert r.text == TEXT and r.rejected[0]["reason"] in ("too_long", "sound", "syllable_count", "mixed_script")


def test_not_found_ambiguous_overlap():
    r = co.apply_edits(TEXT, [E("不存在", "不存再"), E("Ray Chan", "Roichen", "x", "y"),
                              E("正吉坐墊", "正脊坐墊", scope="all"), E("正吉", "正脊", scope="all")])
    reasons = sorted(x["reason"] for x in r.rejected)
    assert reasons == ["ambiguous", "not_found", "overlap"]


def test_scope_all_needs_two_chinese_chars():
    r = co.apply_edits("不好不對", [E("不", "步", scope="all")])
    assert r.rejected[0]["reason"] == "too_short_for_all"


def test_scope_all_count_cap():
    text = "正吉" * 21
    r = co.apply_edits(text, [E("正吉", "正脊", scope="all")])
    assert r.rejected[0]["reason"] == "too_many_occurrences"


def test_total_change_cap_rejects_largest_distance_first():
    # 600 chars -> cap = max(30, 24) = 30; 12 edits x 3 chars = 36 > 30
    names = ["盛夢公", "勝夢公", "聖夢公", "生夢公", "升夢公", "昇夢公",
             "聲夢公", "繩夢公", "省夢公", "剩夢公", "盛孟公", "勝孟公"]
    text = "".join(n + "甲" * 47 for n in names)
    edits = [E(n, "謝孟恭") for n in names]
    r = co.apply_edits(text, edits, check=lambda w, rr: co.phonetic.Verdict(True, "ok", 0.3))
    assert sum(len(a["wrong"]) * a["count"] for a in r.accepted) <= 30
    assert any(x["reason"] == "total_change_cap" for x in r.rejected)


def test_tiny_transcript_still_allows_one_fix():
    r = co.apply_edits("我用Germany查", [E("Germany", "Gemini")])
    assert r.text == "我用Gemini查"


def test_english_matches_whole_words_only():
    r = co.apply_edits("Marcus and Marc met", [E("Marc", "Mark", scope="all")])
    assert r.text == "Marcus and Mark met"


def test_right_containing_wrong_replaces_once():
    r = co.apply_edits("用Gemini跟Gemini", [E("Gemini", "Gemini Pro", scope="all")],
                       check=lambda w, rr: co.phonetic.Verdict(True, "ok", 0))
    assert r.text == "用Gemini Pro跟Gemini Pro"


def test_crlf_preserved():
    r = co.apply_edits("第一行古埃\r\n第二行", [E("古埃", "股癌")])
    assert r.text == "第一行股癌\r\n第二行"


def test_verify_catches_a_broken_assembler(monkeypatch):
    real = co._assemble

    def bad_assemble(text, spans):
        return real(text, spans) + "多一個字"
    monkeypatch.setattr(co, "_assemble", bad_assemble)
    r = co.apply_edits(TEXT, [E("古埃", "股癌", "收聽", ",我是"), E("不存在", "不存再")])
    assert r.text == TEXT  # verification failed -> whole copy discarded
    assert r.accepted == []
    reasons = sorted(x["reason"] for x in r.rejected)
    assert reasons == ["not_found", "verify_failed"]


ACCEPT = lambda w, rr: co.phonetic.Verdict(True, "ok", 0.1)  # noqa: E731


def test_verify_checks_source_side(monkeypatch):
    real = co._occurrences
    monkeypatch.setattr(co, "_occurrences", lambda t, w: [s + 1 for s in real(t, w)])
    r = co.apply_edits(TEXT, [E("古埃", "股癌", "收聽", ",我是")])
    assert r.text == TEXT
    assert [x["reason"] for x in r.rejected] == ["verify_failed"]


def test_verify_rejects_overlapping_spans_directly():
    acc = [{"wrong": "ab", "right": "x", "spans": [[0, 2]]},
           {"wrong": "bc", "right": "y", "spans": [[1, 3]]}]
    assert co.verify("abc", "xc", acc) is False


@pytest.mark.parametrize("text,wrong,right", [
    ("ababab甲", "甲", "ab甲"), ("甲ababab", "甲", "甲ab"), ("正吉正吉正吉甲", "甲", "正吉甲"),
    ("哈哈哈哈哈哈乙", "乙", "哈哈乙"), ("aaaa乙", "乙", "aa乙"), ("xyxyxy乙", "乙", "xy乙"),
    ("abcabc甲", "甲", "abc甲"), ("甲乙甲乙甲乙丙", "丙", "甲乙丙")])
def test_insertions_next_to_repeated_text_apply(text, wrong, right):
    r = co.apply_edits(text, [E(wrong, right)], check=ACCEPT)
    assert r.text == text.replace(wrong, right) and len(r.accepted) == 1 and not r.rejected


def test_adjacent_edits_both_apply():
    r = co.apply_edits("甲正吉坐墊乙", [E("正吉", "正脊"), E("坐墊", "做店")], check=ACCEPT)
    assert r.text == "甲正脊做店乙" and len(r.accepted) == 2 and not r.rejected


def test_insertion_at_span_boundary_applies():
    r = co.apply_edits("ab甲ab", [E("甲", "ab甲")], check=ACCEPT)
    assert r.text == "abab甲ab" and len(r.accepted) == 1


def test_scope_all_back_to_back_repeats():
    r = co.apply_edits("正吉正吉正吉", [E("正吉", "正脊", scope="all")])
    assert r.text == "正脊正脊正脊" and r.accepted[0]["count"] == 3


def test_parse_edits_deep_nesting_is_edits_error():
    with pytest.raises(co.EditsError):
        co.parse_edits("[" * 200000 + "]" * 200000)


SLOW = ["[" * 200000 + "]" * 200000, "[" * 20000, "[ " * 200000, "[1," * 20000, '["",' * 20000,
        ("[" * 101 + " ") * 500]


@pytest.mark.parametrize("raw", SLOW)
def test_parse_edits_slow_shapes_fail_fast(raw):
    import time
    t0 = time.time()
    with pytest.raises(co.EditsError):
        co.parse_edits(raw)
    assert time.time() - t0 < 1


def test_parse_edits_oversize_rejected():
    with pytest.raises(co.EditsError):
        co.parse_edits("x" * 1_000_001)


def test_parse_edits_prefers_fenced_block_over_stray_bracket():
    raw = '見 [註] 如下\n```json\n[{"wrong":"a","right":"b"}]\n```\n再 [{"wrong":"x","right":"y"}]'
    assert co.parse_edits(raw)[0]["wrong"] == "a"


def test_parse_edits_deep_prefix_does_not_hide_first_array():
    raw = "[" * 150 + '{"wrong":"古埃","right":"股癌"}]' + ' then [{"wrong":"x","right":"y"}]'
    try:
        got = co.parse_edits(raw)
    except co.EditsError:
        return
    assert got[0]["wrong"] != "x"


def test_parse_edits_unclosed_brackets_is_fast():
    import time
    t0 = time.time()
    with pytest.raises(co.EditsError):
        co.parse_edits("[" * 20000)
    assert time.time() - t0 < 1


def test_empty_wrong_is_malformed():
    r = co.apply_edits(TEXT, [E("", "插入一句話", "收聽", "古埃"), E("  ", "x")], check=ACCEPT)
    assert r.text == TEXT and [x["reason"] for x in r.rejected] == ["malformed", "malformed"]


def test_cap_counts_the_longer_side():
    # wrong 1 char but right 20 chars x 2 edits = 40 > cap 24
    r = co.apply_edits("甲乙" + "丙" * 10, [E("甲", "一二三四五六七八九十一二三四五六七八九十"),
                                       E("乙", "一二三四五六七八九十一二三四五六七八九十")], check=ACCEPT)
    assert len(r.accepted) == 1 and r.rejected[0]["reason"] == "total_change_cap"
    r = co.apply_edits("古埃古埃" + "丙" * 10, [E("古埃", "一二三四五六七八九十一二三四", scope="all")],
                       check=ACCEPT)
    assert r.accepted == [] and r.rejected[0]["reason"] == "total_change_cap"


def test_cap_drops_largest_distance_first():
    names = ["盛夢公", "勝夢公", "聖夢公", "生夢公", "升夢公", "昇夢公",
             "聲夢公", "繩夢公", "省夢公", "剩夢公", "盛孟公", "勝孟公"]
    text = "".join(n + "甲" * 47 for n in names)
    dist = {n: 0.1 + i * 0.03 for i, n in enumerate(names)}
    r = co.apply_edits(text, [E(n, "謝孟恭") for n in names],
                       check=lambda w, rr: co.phonetic.Verdict(True, "ok", dist[w]))
    dropped = {x["wrong"] for x in r.rejected if x["reason"] == "total_change_cap"}
    kept = {a["wrong"] for a in r.accepted}
    assert dropped and kept and max(dist[k] for k in kept) < min(dist[d] for d in dropped)
    assert names[0] in kept and names[-1] in dropped


def test_records_are_whitelisted():
    e = E("古埃", "股癌", "收聽", ",我是")
    e.update(why="x" * 500, evil="payload")
    bad = E("不存在", "不存再")
    bad["evil"] = "payload"
    r = co.apply_edits(TEXT, [e, bad, "z" * 1000])
    assert "evil" not in r.accepted[0] and len(r.accepted[0]["why"]) == 200
    assert all("evil" not in x for x in r.rejected)
    mal = [x for x in r.rejected if x["reason"] == "malformed"][0]
    assert len(mal["edit"]) <= 200


def test_edit_count_cap():
    edits = [E("不存在", "不存再")] * 500 + [E("古埃", "股癌", "收聽", ",我是")]
    r = co.apply_edits(TEXT, edits)
    assert r.rejected[-1]["reason"] == "too_many_edits" and r.accepted == []


def test_cr_in_wrong_or_right_is_too_long():
    r = co.apply_edits("甲\r乙", [E("甲\r", "步"), E("乙", "步\r")], check=ACCEPT)
    assert [x["reason"] for x in r.rejected] == ["too_long", "too_long"]


def test_once_single_hit_with_wrong_context_accepted():
    r = co.apply_edits(TEXT, [E("古埃", "股癌", "不對", "也不對")])
    assert r.text.startswith("歡迎收聽股癌")


def test_once_english_changes_only_standalone_word():
    r = co.apply_edits("Raymond and Ray met", [E("Ray", "Rey")])
    assert r.text == "Raymond and Rey met"


def test_bad_items_rejected_individually():
    r = co.apply_edits(TEXT, [{"wrong": "古埃"}, "nonsense", E("古埃", "股癌")])
    assert r.text.startswith("歡迎收聽股癌")
    assert sorted(x["reason"] for x in r.rejected) == ["malformed", "malformed"]


def _entry(tmp_path, text="歡迎收聽古埃,我是盛夢公。"):
    d = tmp_path / "entry"
    d.mkdir()
    (d / "transcript.txt").write_text(text, encoding="utf-8")
    (d / "meta.json").write_text(json.dumps({"transcript_path": str(d / "transcript.txt")}))
    return d


def _run(*argv, stdin=None, monkeypatch=None, capsys=None):
    if stdin is not None:
        monkeypatch.setattr(sys, "stdin", __import__("io").StringIO(stdin))
    rc = co.main(list(argv))
    return rc, json.loads(capsys.readouterr().out.strip().splitlines()[-1])


EDITS = json.dumps([E("古埃", "股癌", "收聽", ",我是")])


def test_reference_key_ignores_nonce_and_order():
    k1 = co.reference_key([("真真", [])], {"title": "t", "channel": "c"})
    k2 = co.reference_key([("真真", [])], {"channel": "c", "title": "t"})
    assert k1 == k2 and k1 != co.reference_key([], {"title": "t", "channel": "c"})


def test_check_pending_then_apply_then_cached(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("AUDIO_TLDR_GLOSSARY", str(tmp_path / "none.txt"))
    d = _entry(tmp_path)
    rc, out = _run("check", str(d), monkeypatch=monkeypatch, capsys=capsys)
    assert rc == 0 and out["status"] == "pending" and Path(out["reference_path"]).parent == d
    rc, out = _run("apply", str(d), "--edits", "-", "--model", "sonnet", stdin=EDITS,
                   monkeypatch=monkeypatch, capsys=capsys)
    assert out["accepted"] == 1 and Path(out["corrected_path"]).read_text(encoding="utf-8").startswith("歡迎收聽股癌")
    assert (d / "transcript.txt").read_text(encoding="utf-8") == "歡迎收聽古埃,我是盛夢公。"
    rc, out = _run("check", str(d), monkeypatch=monkeypatch, capsys=capsys)
    assert out["status"] == "cached"


def test_line_break_upgrade_makes_check_pending_once_then_cached(tmp_path, monkeypatch, capsys):
    """Seam: the hit-path upgrade rewrites transcript.txt, so its sha (the correction key) changes."""
    monkeypatch.setenv("AUDIO_TLDR_GLOSSARY", str(tmp_path / "none.txt"))
    seg1, seg2 = "嗯" * 300 + "古埃。", "啊" * 300 + "。"
    d = _entry(tmp_path, seg1 + seg2)
    (d / "segments.json").write_text(json.dumps([{"start": 0, "end": 1, "text": seg1},
                                                 {"start": 1, "end": 2, "text": seg2}]), encoding="utf-8")
    edits = json.dumps([E("古埃", "股癌", "嗯", "。")])
    _, out = _run("check", str(d), monkeypatch=monkeypatch, capsys=capsys)
    assert out["status"] == "pending"
    _run("apply", str(d), "--edits", "-", "--model", "sonnet", stdin=edits, monkeypatch=monkeypatch, capsys=capsys)
    _, out = _run("check", str(d), monkeypatch=monkeypatch, capsys=capsys)
    assert out["status"] == "cached"
    meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
    assert co.transcribe.upgrade_transcript_lines(d, meta) is True
    assert "\n" in (d / "transcript.txt").read_text(encoding="utf-8")
    _, out = _run("check", str(d), monkeypatch=monkeypatch, capsys=capsys)
    assert out["status"] == "pending"            # new sha: correction runs once
    rc, out = _run("apply", str(d), "--edits", "-", "--model", "sonnet", stdin=edits,
                   monkeypatch=monkeypatch, capsys=capsys)
    assert out["accepted"] == 1
    _, out = _run("check", str(d), monkeypatch=monkeypatch, capsys=capsys)
    assert out["status"] == "cached"


def test_glossary_change_invalidates(tmp_path, monkeypatch, capsys):
    g = tmp_path / "g.txt"
    monkeypatch.setenv("AUDIO_TLDR_GLOSSARY", str(g))
    d = _entry(tmp_path)
    _run("apply", str(d), "--edits", "-", "--model", "sonnet", stdin=EDITS, monkeypatch=monkeypatch, capsys=capsys)
    g.write_text("股癌\n", encoding="utf-8")
    _, out = _run("check", str(d), monkeypatch=monkeypatch, capsys=capsys)
    assert out["status"] == "pending"


def test_other_model_copy_is_reused(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("AUDIO_TLDR_GLOSSARY", str(tmp_path / "none.txt"))
    d = _entry(tmp_path)
    _run("apply", str(d), "--edits", "-", "--model", "gpt-5.6-terra", stdin=EDITS, monkeypatch=monkeypatch, capsys=capsys)
    _, out = _run("check", str(d), monkeypatch=monkeypatch, capsys=capsys)
    assert out["status"] == "cached"


def test_missing_commit_marker_means_no_cache(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("AUDIO_TLDR_GLOSSARY", str(tmp_path / "none.txt"))
    d = _entry(tmp_path)
    _run("apply", str(d), "--edits", "-", "--model", "sonnet", stdin=EDITS, monkeypatch=monkeypatch, capsys=capsys)
    (d / "transcript.corrected.txt").write_text("被別人改過", encoding="utf-8")
    _, out = _run("check", str(d), monkeypatch=monkeypatch, capsys=capsys)
    assert out["status"] == "pending"  # recorded sha no longer matches


def test_newer_version_is_used_not_overwritten(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("AUDIO_TLDR_GLOSSARY", str(tmp_path / "none.txt"))
    d = _entry(tmp_path)
    _run("apply", str(d), "--edits", "-", "--model", "sonnet", stdin=EDITS, monkeypatch=monkeypatch, capsys=capsys)
    c = json.loads((d / "corrections.json").read_text(encoding="utf-8"))
    c["key"]["correction_version"] = co.CORRECTION_VERSION + 1
    (d / "corrections.json").write_text(json.dumps(c), encoding="utf-8")
    _, out = _run("check", str(d), monkeypatch=monkeypatch, capsys=capsys)
    assert out["status"] == "cached"
    _run("apply", str(d), "--edits", "-", "--model", "sonnet", stdin="[]", monkeypatch=monkeypatch, capsys=capsys)
    assert json.loads((d / "corrections.json").read_text(encoding="utf-8"))["key"]["correction_version"] == co.CORRECTION_VERSION + 1


def test_skip_when_no_checker(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(co.phonetic, "available", lambda: {"zh": False, "en": False})
    d = _entry(tmp_path)
    _, out = _run("check", str(d), monkeypatch=monkeypatch, capsys=capsys)
    assert out["status"] == "skip"


MIXED = "歡迎收聽古埃,我是盛夢公。Ray Chan很好。"
MIXED_EDITS = json.dumps([E("古埃", "股癌", "收聽", ",我是"), E("Ray", "Rey", "", " Chan")])


def _mixed_apply(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("AUDIO_TLDR_GLOSSARY", str(tmp_path / "none.txt"))
    monkeypatch.setattr(co.phonetic, "available", lambda: {"zh": True, "en": False})
    d = _entry(tmp_path, MIXED)
    _, out = _run("apply", str(d), "--edits", "-", "--model", "sonnet", stdin=MIXED_EDITS,
                  monkeypatch=monkeypatch, capsys=capsys)
    return d, out


def test_partial_checker_keeps_passed_edits_and_records_checkers(tmp_path, monkeypatch, capsys):
    d, out = _mixed_apply(tmp_path, monkeypatch, capsys)
    assert out["accepted"] == 1 and out["unavailable"] == ["en"]
    assert Path(out["corrected_path"]).read_text(encoding="utf-8").startswith("歡迎收聽股癌")
    c = json.loads((d / "corrections.json").read_text(encoding="utf-8"))
    assert c["checkers"] == {"zh": True, "en": False}
    assert any(r.get("reason") == "checker_unavailable" for r in c["rejected"])


def test_partial_copy_is_cached_while_checker_stays_missing(tmp_path, monkeypatch, capsys):
    d, _ = _mixed_apply(tmp_path, monkeypatch, capsys)
    _, out = _run("check", str(d), monkeypatch=monkeypatch, capsys=capsys)
    assert out["status"] == "cached"


def test_installing_missing_checker_triggers_recompute(tmp_path, monkeypatch, capsys):
    d, _ = _mixed_apply(tmp_path, monkeypatch, capsys)
    monkeypatch.setattr(co.phonetic, "available", lambda: {"zh": True, "en": True})
    _, out = _run("check", str(d), monkeypatch=monkeypatch, capsys=capsys)
    assert out["status"] == "pending"


def test_cached_copy_survives_checker_uninstall(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("AUDIO_TLDR_GLOSSARY", str(tmp_path / "none.txt"))
    d = _entry(tmp_path)
    _run("apply", str(d), "--edits", "-", "--model", "sonnet", stdin=EDITS, monkeypatch=monkeypatch, capsys=capsys)
    monkeypatch.setattr(co.phonetic, "available", lambda: {"zh": False, "en": False})
    _, out = _run("check", str(d), monkeypatch=monkeypatch, capsys=capsys)
    assert out["status"] == "cached"


def test_missing_transcript_keeps_json_contract(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("AUDIO_TLDR_GLOSSARY", str(tmp_path / "none.txt"))
    d = tmp_path / "empty"
    d.mkdir()
    rc, out = _run("check", str(d), monkeypatch=monkeypatch, capsys=capsys)
    assert rc == 0 and out == {"status": "skip", "reason": "no_transcript"}
    rc, out = _run("apply", str(d), "--edits", "-", "--model", "m", stdin="[]", monkeypatch=monkeypatch, capsys=capsys)
    assert rc == 0 and out == {"corrected_path": None, "reason": "no_transcript"}


def test_unreadable_edits_file(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("AUDIO_TLDR_GLOSSARY", str(tmp_path / "none.txt"))
    d = _entry(tmp_path)
    rc, out = _run("apply", str(d), "--edits", str(tmp_path / "nope.json"), "--model", "m",
                   monkeypatch=monkeypatch, capsys=capsys)
    assert rc == 0 and out == {"corrected_path": None, "reason": "edits_unreadable"}


@pytest.mark.parametrize("junk", ['{"key": [], "corrected_sha256": "x"}', "[1, 2]", '{"key": "s"}'])
def test_corrupt_corrections_json_is_no_cache(tmp_path, monkeypatch, capsys, junk):
    monkeypatch.setenv("AUDIO_TLDR_GLOSSARY", str(tmp_path / "none.txt"))
    d = _entry(tmp_path)
    _run("apply", str(d), "--edits", "-", "--model", "sonnet", stdin=EDITS, monkeypatch=monkeypatch, capsys=capsys)
    (d / "corrections.json").write_text(junk, encoding="utf-8")
    _, out = _run("check", str(d), monkeypatch=monkeypatch, capsys=capsys)
    assert out["status"] == "pending"
    rc, out = _run("apply", str(d), "--edits", "-", "--model", "sonnet", stdin=EDITS, monkeypatch=monkeypatch, capsys=capsys)
    assert rc == 0 and out["accepted"] == 1


def test_deleted_corrections_json_means_no_cache(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("AUDIO_TLDR_GLOSSARY", str(tmp_path / "none.txt"))
    d = _entry(tmp_path)
    _run("apply", str(d), "--edits", "-", "--model", "sonnet", stdin=EDITS, monkeypatch=monkeypatch, capsys=capsys)
    (d / "corrections.json").unlink()
    assert (d / "transcript.corrected.txt").exists()
    _, out = _run("check", str(d), monkeypatch=monkeypatch, capsys=capsys)
    assert out["status"] == "pending"


def test_nothing_to_check_reason(tmp_path, monkeypatch, capsys):
    d = _entry(tmp_path, "123 456 。。。")
    _, out = _run("check", str(d), monkeypatch=monkeypatch, capsys=capsys)
    assert out == {"status": "skip", "reason": "nothing_to_check"}


def test_cli_runs_as_a_script(tmp_path):
    """Every subcommand must still work when correct.py runs as a file (later
    tasks append functions; a definition after the __main__ guard breaks this)."""
    import subprocess
    d = _entry(tmp_path)
    env = {**__import__("os").environ, "AUDIO_TLDR_GLOSSARY": str(tmp_path / "none.txt")}
    p = subprocess.run([sys.executable, str(SCRIPTS / "correct.py"), "check", str(d)],
                       capture_output=True, text=True, env=env, timeout=60)
    assert p.returncode == 0, p.stderr
    assert json.loads(p.stdout.strip().splitlines()[-1])["status"] in ("pending", "skip")


def test_broken_edits_fall_back(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("AUDIO_TLDR_GLOSSARY", str(tmp_path / "none.txt"))
    d = _entry(tmp_path)
    rc, out = _run("apply", str(d), "--edits", "-", "--model", "sonnet", stdin="抱歉我無法", monkeypatch=monkeypatch, capsys=capsys)
    assert rc == 0 and out["corrected_path"] is None and out["reason"] == "no_edit_list"


SRT = "1\n00:00:00,000 --> 00:00:02,000\n歡迎收聽古埃\n\n2\n00:00:02,000 --> 00:00:04,000\n我是盛夢\n\n3\n00:00:04,000 --> 00:00:05,000\n公,本集\n"


def test_subtitle_applies_within_cues_and_skips_cross_cue():
    acc = [{"wrong": "古埃", "right": "股癌", "scope": "once", "before": "收聽", "after": ","},
           {"wrong": "盛夢公", "right": "謝孟恭", "scope": "once", "before": "我是", "after": ","}]
    out, applied, skipped = co.apply_to_subtitle(SRT, acc)
    assert "歡迎收聽股癌" in out and "盛夢" in out  # second edit spans two cues
    assert (applied, skipped) == (1, 1)
    assert out.count("-->") == 3  # timing lines untouched


def test_subtitle_english_whole_word_in_cue():
    srt = "1\n00:00:00,000 --> 00:00:02,000\nMarcus and Marc met\n"
    out, applied, _ = co.apply_to_subtitle(srt, [{"wrong": "Marc", "right": "Mark", "scope": "all"}])
    assert "Marcus and Mark met" in out and applied == 1
    out, applied, skipped = co.apply_to_subtitle(
        "1\n00:00:00,000 --> 00:00:02,000\nMarcus only\n", [{"wrong": "Marc", "right": "Mark", "scope": "once"}])
    assert "Marcus only" in out and (applied, skipped) == (0, 1)


def test_subtitle_end_to_end_via_main(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("AUDIO_TLDR_GLOSSARY", str(tmp_path / "none.txt"))
    d = _entry(tmp_path)
    (d / "transcript.srt").write_bytes(SRT.encode("utf-8"))
    original = (d / "transcript.srt").read_bytes()
    _run("apply", str(d), "--edits", "-", "--model", "sonnet", stdin=EDITS, monkeypatch=monkeypatch, capsys=capsys)
    rc, out = _run("subtitle", str(d), "--format", "srt", monkeypatch=monkeypatch, capsys=capsys)
    assert rc == 0 and out["applied"] == 1 and out["skipped"] == 0
    got = Path(out["subtitle_path"])
    assert got != d / "transcript.srt" and got.is_file()
    text = got.read_text(encoding="utf-8")
    assert "歡迎收聽股癌" in text
    assert [l for l in text.splitlines() if "-->" in l] == [l for l in SRT.splitlines() if "-->" in l]
    assert (d / "transcript.srt").read_bytes() == original


def test_subtitle_without_corrections_returns_original(tmp_path, monkeypatch, capsys):
    d = _entry(tmp_path)
    (d / "transcript.srt").write_text(SRT, encoding="utf-8")
    rc, out = _run("subtitle", str(d), "--format", "srt", monkeypatch=monkeypatch, capsys=capsys)
    assert rc == 0 and out == {"subtitle_path": str(d / "transcript.srt"), "applied": 0, "skipped": 0}


def test_subtitle_no_meta_and_missing_source(tmp_path, monkeypatch, capsys):
    d = tmp_path / "empty"
    d.mkdir()
    rc, out = _run("subtitle", str(d), "--format", "vtt", monkeypatch=monkeypatch, capsys=capsys)
    assert rc == 0 and out == {"subtitle_path": None, "reason": "no_meta"}
    d2 = _entry(tmp_path)
    rc, out = _run("subtitle", str(d2), "--format", "vtt", monkeypatch=monkeypatch, capsys=capsys)
    assert rc == 2 and out["subtitle_path"] is None and out["error"]


def test_unavailable_script_falls_back_to_right_side(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("AUDIO_TLDR_GLOSSARY", str(tmp_path / "none.txt"))
    monkeypatch.setattr(co.phonetic, "available", lambda: {"zh": False, "en": True})
    d = _entry(tmp_path, "全館52折")
    _, out = _run("apply", str(d), "--edits", "-", "--model", "sonnet",
                  stdin=json.dumps([E("52", "無二", "全館", "折")]), monkeypatch=monkeypatch, capsys=capsys)
    assert out["unavailable"] == ["zh"]


def _cue(n, text, t0=0):
    return f"{n}\n00:00:0{t0},000 --> 00:00:0{t0 + 1},000\n{text}\n"


def test_once_edit_lands_on_the_cue_whose_context_matches():
    srt = _cue(1, "古埃是什麼") + "\n" + _cue(2, "歡迎收聽古埃,今天", 1)
    out, applied, skipped = co.apply_to_subtitle(
        srt, [{"wrong": "古埃", "right": "股癌", "scope": "once", "before": "收聽", "after": ","}])
    assert "古埃是什麼" in out and "歡迎收聽股癌,今天" in out and (applied, skipped) == (1, 0)


def test_once_edit_ambiguous_across_cues_is_skipped():
    srt = _cue(1, "古埃一") + "\n" + _cue(2, "古埃二", 1)
    out, applied, skipped = co.apply_to_subtitle(
        srt, [{"wrong": "古埃", "right": "股癌", "scope": "once", "before": "收聽", "after": ","}])
    assert out == srt and (applied, skipped) == (0, 1)


def test_edits_are_simultaneous_not_chained():
    srt = _cue(1, "甲乙丙")
    acc = [{"wrong": "甲", "right": "乙乙", "scope": "all"}, {"wrong": "乙", "right": "X", "scope": "all"}]
    out, applied, _ = co.apply_to_subtitle(srt, acc)
    assert "乙乙X丙" in out and applied == 2


def test_digit_only_caption_line_is_editable_but_cue_index_is_not():
    srt = _cue(1, "52")
    out, applied, _ = co.apply_to_subtitle(srt, [{"wrong": "52", "right": "無二", "scope": "all"}])
    assert out.startswith("1\n") and out.endswith("無二\n") and applied == 1


def test_vtt_header_note_and_cue_id_are_not_text():
    vtt = "WEBVTT\n\nNOTE Marc wrote this\n\nMarc\n00:00:00.000 --> 00:00:01.000\nMarc speaks\n"
    out, applied, _ = co.apply_to_subtitle(vtt, [{"wrong": "Marc", "right": "Mark", "scope": "all"}])
    assert "NOTE Marc wrote this" in out and "\nMarc\n00:00" in out and "Mark speaks" in out and applied == 1


def test_subtitle_ignores_tampered_corrected_transcript(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("AUDIO_TLDR_GLOSSARY", str(tmp_path / "none.txt"))
    d = _entry(tmp_path)
    (d / "transcript.srt").write_text(SRT, encoding="utf-8")
    _run("apply", str(d), "--edits", "-", "--model", "sonnet", stdin=EDITS, monkeypatch=monkeypatch, capsys=capsys)
    corrected = co.transcribe.derived_file(d, "corrected")
    corrected.write_text(corrected.read_text(encoding="utf-8") + "x", encoding="utf-8")
    rc, out = _run("subtitle", str(d), "--format", "srt", monkeypatch=monkeypatch, capsys=capsys)
    assert rc == 0 and out["reason"] == "no_valid_corrections" and out["applied"] == 0
    assert out["subtitle_path"] == str(d / "transcript.srt")
    assert not co.transcribe.derived_file(d, "corrected_srt").exists()


def test_prompt_file_exists_and_asks_for_json_only():
    t = co.PROMPT_PATH.read_text(encoding="utf-8")
    assert "ONLY a JSON array" in t and "untrusted" in t


def test_prompt_forbids_unifying_name_spellings_by_frequency():
    t = " ".join(co.PROMPT_PATH.read_text(encoding="utf-8").split())
    assert "another spelling the transcript also uses" in t and "not evidence" in t


def test_chunks_overlap_and_cover():
    text = "字" * 13000
    cs = co.chunks(text, size=6000)
    assert len(cs) == 3 and all(len(c) <= 6000 for c in cs)
    assert sum(len(c) for c in cs) - 200 * (len(cs) - 1) == len(text)


def test_ollama_path_merges_chunk_edits(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("AUDIO_TLDR_GLOSSARY", str(tmp_path / "none.txt"))
    d = _entry(tmp_path)
    monkeypatch.setattr(co.digest, "call_ollama_chat", lambda host, model, messages, **kw: EDITS)
    rc, out = _run("ollama", str(d), "--model", "gemma4:26b", monkeypatch=monkeypatch, capsys=capsys)
    assert rc == 0 and out["accepted"] == 1
    rec = json.loads(co.transcribe.derived_file(d, "corrections").read_text(encoding="utf-8"))
    assert rec["model"] == "ollama:gemma4:26b"


def test_ollama_error_exits_2_without_writing(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("AUDIO_TLDR_GLOSSARY", str(tmp_path / "none.txt"))
    d = _entry(tmp_path)

    def boom(*a, **k):
        raise co.digest.OllamaUnreachable("Ollama unreachable at http://x")
    monkeypatch.setattr(co.digest, "call_ollama_chat", boom)
    assert co.main(["ollama", str(d), "--model", "m"]) == 2
    assert "unreachable" in capsys.readouterr().err
    assert not co.transcribe.derived_file(d, "corrected").exists()


def test_ollama_chunk_without_array_is_skipped(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("AUDIO_TLDR_GLOSSARY", str(tmp_path / "none.txt"))
    d = _entry(tmp_path, "歡迎收聽古埃,我是盛夢公。" + "。" * 7000)
    replies = iter(["sorry, no list", EDITS, "[]"])
    monkeypatch.setattr(co.digest, "call_ollama_chat", lambda h, m, msgs, **kw: next(replies))
    rc, out = _run("ollama", str(d), "--model", "m", monkeypatch=monkeypatch, capsys=capsys)
    assert rc == 0 and out["accepted"] == 1  # chunk 1 had no array, chunk 2 supplied the edit


def test_ollama_no_transcript_and_cache(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("AUDIO_TLDR_GLOSSARY", str(tmp_path / "none.txt"))
    d = tmp_path / "e"
    d.mkdir()
    rc, out = _run("ollama", str(d), "--model", "m", monkeypatch=monkeypatch, capsys=capsys)
    assert rc == 0 and out == {"corrected_path": None, "reason": "no_transcript"}
    d2 = _entry(tmp_path)
    _run("apply", str(d2), "--edits", "-", "--model", "x", stdin=EDITS, monkeypatch=monkeypatch, capsys=capsys)

    def never(*a, **k):
        raise AssertionError("must not call Ollama on a cache hit")
    monkeypatch.setattr(co.digest, "call_ollama_chat", never)
    rc, out = _run("ollama", str(d2), "--model", "m", monkeypatch=monkeypatch, capsys=capsys)
    assert rc == 0 and out["cached"] is True


def test_vtt_cue_id_starting_with_note_is_not_skipped():
    vtt = "WEBVTT\n\nNOTES1\n00:00:00.000 --> 00:00:01.000\nMarc speaks\n\nNOTE\nMarc\n\nSTYLE\n::cue{}\n"
    out, applied, _ = co.apply_to_subtitle(vtt, [{"wrong": "Marc", "right": "Mark", "scope": "all"}])
    assert "Mark speaks" in out and "NOTE\nMarc\n" in out and applied == 1


def test_crlf_subtitle_round_trips_except_edited_span():
    srt = "1\r\n00:00:00,000 --> 00:00:01,000\r\n歡迎收聽古埃\r\n第二行\r\n\r\n2\r\n00:00:01,000 --> 00:00:02,000\r\n我說古埃再見\r\n"
    acc = [{"wrong": "古埃", "right": "股癌", "before": "收聽", "after": "第二", "scope": "once"}]
    out, applied, _ = co.apply_to_subtitle(srt, acc)
    assert applied == 1 and out == srt.replace("收聽古埃", "收聽股癌")


class _Resp:
    def __init__(self, payload):
        self._p = json.dumps(payload).encode()

    def read(self):
        return self._p

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_ollama_payload_never_truncates_and_sets_context(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("AUDIO_TLDR_GLOSSARY", str(tmp_path / "none.txt"))
    d = _entry(tmp_path)
    bodies = []
    monkeypatch.setattr(co.digest, "ollama_num_ctx", lambda host, model: 32768)

    def fake_urlopen(req, timeout=None):
        bodies.append(json.loads(req.data.decode()))
        return _Resp({"message": {"content": "[]"}})
    monkeypatch.setattr(co.digest.urllib.request, "urlopen", fake_urlopen)
    rc, _ = _run("ollama", str(d), "--model", "m", monkeypatch=monkeypatch, capsys=capsys)
    assert rc == 0 and bodies and bodies[0]["truncate"] is False
    assert bodies[0]["options"]["num_ctx"] == 32768
    assert "num_predict" not in bodies[0]["options"]


def test_ollama_context_overflow_400_exits_2_nothing_written(tmp_path, monkeypatch, capsys):
    import io
    monkeypatch.setenv("AUDIO_TLDR_GLOSSARY", str(tmp_path / "none.txt"))
    d = _entry(tmp_path)

    def fake_urlopen(req, timeout=None):
        body = json.dumps({"error": "request (9000 tokens) exceeds the available context size (4096 tokens)"})
        raise co.digest.urllib.error.HTTPError(req.full_url, 400, "Bad Request", None, io.BytesIO(body.encode()))
    monkeypatch.setattr(co.digest.urllib.request, "urlopen", fake_urlopen)
    assert co.main(["ollama", str(d), "--model", "m"]) == 2
    assert "exceeds the available context size" in capsys.readouterr().err
    assert not co.transcribe.derived_file(d, "corrected").exists()
    assert not co.transcribe.derived_file(d, "corrections").exists()


def test_ollama_same_all_edit_from_two_chunks_is_deduped(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("AUDIO_TLDR_GLOSSARY", str(tmp_path / "none.txt"))
    d = _entry(tmp_path, "歡迎收聽古埃,我是盛夢公。" + "。" * 7000 + "古埃再見")
    r1 = json.dumps([E("古埃", "股癌", "收聽", ",我是", "all")])
    r2 = json.dumps([{**E("古埃", "股癌", "。。。。", "再見", "all"), "why": "other"}])
    replies = iter([r1, r2])
    monkeypatch.setattr(co.digest, "call_ollama_chat", lambda h, m, msgs, **kw: next(replies))
    rc, out = _run("ollama", str(d), "--model", "m", monkeypatch=monkeypatch, capsys=capsys)
    assert rc == 0 and out["accepted"] == 1
    rec = json.loads(co.transcribe.derived_file(d, "corrections").read_text(encoding="utf-8"))
    assert not any(r.get("reason") == "overlap" for r in rec["rejected"])


def test_reference_key_changes_with_creator():
    base = {"title": "t", "channel": "c"}
    k0 = co.reference_key([], base)
    k1 = co.reference_key([], {**base, "creator": "真真"})
    k2 = co.reference_key([], {**base, "creator": "珍珍"})
    assert len({k0, k1, k2}) == 3




def test_reference_key_old_context_without_creator_matches_creator_none():
    old = {"title": "t", "channel": "c"}
    assert co.reference_key([], old) == co.reference_key([], {**old, "creator": None})
    assert co.reference_key([], old) != co.reference_key([], {**old, "creator": "真真"})


# --- final review fixes ---


def _lang_entry(tmp_path, language, text):
    d = _entry(tmp_path, text)
    (d / "meta.json").write_text(json.dumps({"transcript_path": str(d / "transcript.txt"),
                                             "language": language}))
    return d


def test_unsupported_language_is_skipped_everywhere(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("AUDIO_TLDR_GLOSSARY", str(tmp_path / "none.txt"))
    d = _lang_entry(tmp_path, "ja", "今日は天気がいいですね。古埃の話をしましょう。")
    rc, out = _run("check", str(d), monkeypatch=monkeypatch, capsys=capsys)
    assert rc == 0 and out == {"status": "skip", "reason": "unsupported_language"}
    rc, out = _run("apply", str(d), "--edits", "-", "--model", "m", stdin=EDITS,
                   monkeypatch=monkeypatch, capsys=capsys)
    assert rc == 0 and out == {"corrected_path": None, "reason": "unsupported_language"}
    monkeypatch.setattr(co.digest, "call_ollama_chat", lambda *a, **k: EDITS)
    rc, out = _run("ollama", str(d), "--model", "m", monkeypatch=monkeypatch, capsys=capsys)
    assert rc == 0 and out == {"corrected_path": None, "reason": "unsupported_language"}
    assert not co.transcribe.derived_file(d, "corrected").exists()
    assert not co.transcribe.derived_file(d, "corrections").exists()


@pytest.mark.parametrize("language,text", [("zh", "歡迎收聽古埃。"), ("yue", "歡迎收聽古埃。"),
                                           ("en", "Welcome to the Ray Chan show."), (None, "歡迎收聽古埃。")])
def test_supported_or_unknown_language_is_pending(tmp_path, monkeypatch, capsys, language, text):
    monkeypatch.setenv("AUDIO_TLDR_GLOSSARY", str(tmp_path / "none.txt"))
    d = _lang_entry(tmp_path, language, text)
    _, out = _run("check", str(d), monkeypatch=monkeypatch, capsys=capsys)
    assert out["status"] == "pending"


def test_ollama_total_parse_failure_stores_nothing(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("AUDIO_TLDR_GLOSSARY", str(tmp_path / "none.txt"))
    d = _entry(tmp_path)
    monkeypatch.setattr(co.digest, "call_ollama_chat", lambda *a, **k: "sorry, no list")
    rc, out = _run("ollama", str(d), "--model", "m", monkeypatch=monkeypatch, capsys=capsys)
    assert rc == 0 and out == {"corrected_path": None, "reason": "no_edit_list"}
    assert not co.transcribe.derived_file(d, "corrected").exists()
    assert not co.transcribe.derived_file(d, "corrections").exists()


def test_ollama_partial_parse_failure_is_recorded(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("AUDIO_TLDR_GLOSSARY", str(tmp_path / "none.txt"))
    d = _entry(tmp_path, "歡迎收聽古埃,我是盛夢公。" + "。" * 7000)
    replies = iter(["sorry, no list", EDITS, "[]"])
    monkeypatch.setattr(co.digest, "call_ollama_chat", lambda h, m, msgs, **kw: next(replies))
    rc, out = _run("ollama", str(d), "--model", "m", monkeypatch=monkeypatch, capsys=capsys)
    assert out["chunks_unparsed"] == 1 and out["chunks"] == len(co.chunks(d.joinpath("transcript.txt").read_text(encoding="utf-8")))
    rec = json.loads(co.transcribe.derived_file(d, "corrections").read_text(encoding="utf-8"))
    assert rec["chunks_unparsed"] == 1 and rec["chunks"] == out["chunks"]


def test_symbols_and_control_characters_cannot_be_added():
    for right in ["選手‮​！！", "選手​", "選手！", "選手‮", "選手 "]:
        res = co.apply_edits("今天選手很強", [E("選手", right)], check=lambda a, b: co.phonetic.Verdict(True, "ok", 0))
        assert res.accepted == [] and res.rejected[0]["reason"] in ("malformed", "added_symbols"), right
    res = co.apply_edits("今天選手很強", [E("選手", "選手​")], check=lambda a, b: co.phonetic.Verdict(True, "ok", 0))
    assert res.rejected[0]["reason"] == "malformed"
    res = co.apply_edits("今天選手很強", [E("選手", "選手！！")], check=lambda a, b: co.phonetic.Verdict(True, "ok", 0))
    assert res.rejected[0]["reason"] == "added_symbols"


def test_dropping_or_keeping_punctuation_still_applies():
    assert co.apply_edits("節目Ray Chan來了", [E("Ray Chan", "Roichen")]).accepted
    assert co.apply_edits("今天正吉很好", [E("正吉", "正脊")]).accepted
    assert co.apply_edits("歡迎收聽古埃,我是", [E("古埃,", "股癌,")]).accepted


def test_newer_version_with_other_key_scheme_is_cached(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("AUDIO_TLDR_GLOSSARY", str(tmp_path / "none.txt"))
    d = _entry(tmp_path)
    _run("apply", str(d), "--edits", "-", "--model", "sonnet", stdin=EDITS, monkeypatch=monkeypatch, capsys=capsys)
    c = json.loads((d / "corrections.json").read_text(encoding="utf-8"))
    c["key"]["correction_version"] = co.CORRECTION_VERSION + 1
    c["key"]["reference_key"] = "a-different-scheme"
    (d / "corrections.json").write_text(json.dumps(c), encoding="utf-8")
    _, out = _run("check", str(d), monkeypatch=monkeypatch, capsys=capsys)
    assert out["status"] == "cached" and out["corrected_path"].endswith("transcript.corrected.txt")
    (d / "transcript.corrected.txt").write_text("changed", encoding="utf-8")
    _, out = _run("check", str(d), monkeypatch=monkeypatch, capsys=capsys)
    assert out["status"] == "pending"


def test_subtitle_skips_corrupt_accepted_records(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("AUDIO_TLDR_GLOSSARY", str(tmp_path / "none.txt"))
    d = _entry(tmp_path)
    (d / "transcript.srt").write_bytes(SRT.encode("utf-8"))
    _run("apply", str(d), "--edits", "-", "--model", "sonnet", stdin=EDITS, monkeypatch=monkeypatch, capsys=capsys)
    c = json.loads((d / "corrections.json").read_text(encoding="utf-8"))
    c["accepted"] = [{"right": "x"}, {"wrong": 5, "right": "y"}, "junk", None] + c["accepted"]
    (d / "corrections.json").write_text(json.dumps(c), encoding="utf-8")
    rc, out = _run("subtitle", str(d), "--format", "srt", monkeypatch=monkeypatch, capsys=capsys)
    assert rc == 0 and out["applied"] == 1 and out["skipped"] == 4


def test_context_defaults_to_the_entry_context_file(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("AUDIO_TLDR_GLOSSARY", str(tmp_path / "none.txt"))
    d = _entry(tmp_path)
    (d / "context.json").write_text(json.dumps({"title": "股癌 EP1", "channel": "c"}), encoding="utf-8")
    _run("apply", str(d), "--edits", "-", "--model", "sonnet", "--context", str(d / "context.json"),
         stdin=EDITS, monkeypatch=monkeypatch, capsys=capsys)
    _, out = _run("check", str(d), monkeypatch=monkeypatch, capsys=capsys)
    assert out["status"] == "cached"
    _, out = _run("check", str(d), "--context", str(d / "context.json"), monkeypatch=monkeypatch, capsys=capsys)
    assert out["status"] == "cached"


# --- usage log ---


def test_usage_appends_whitelisted_fields(tmp_path, capsys):
    d = _entry(tmp_path)
    assert co.main(["usage", str(d), "--json", json.dumps(
        {"phase": "correct", "path": "subagent", "model": "sonnet", "total": 12345,
         "transcript": "不該被記下"})]) == 0
    co.main(["usage", str(d), "--json", json.dumps({"phase": "digest", "path": "inline",
                                                     "source": "unavailable"})])
    lines = [json.loads(l) for l in (d / "usage.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [l["phase"] for l in lines] == ["correct", "digest"]
    assert lines[0]["v"] == 1 and "transcript" not in lines[0] and lines[0]["input"] is None
    assert lines[0]["date"]
    assert lines[1]["total"] is None and lines[1]["source"] == "unavailable"


@pytest.mark.parametrize("bad", ["[1,2]", "not json", "null"])
def test_usage_rejects_non_object(tmp_path, bad):
    d = _entry(tmp_path)
    assert co.main(["usage", str(d), "--json", bad]) == 2
    assert not (d / "usage.jsonl").exists()


def test_usage_survives_a_fresh_transcription(tmp_path):
    d = _entry(tmp_path)
    co.main(["usage", str(d), "--json", json.dumps({"phase": "correct", "total": 1})])
    co.transcribe.derived_file(d, "corrected").write_text("x", encoding="utf-8")
    co.transcribe.remove_correction_files(d)
    assert not co.transcribe.derived_file(d, "corrected").exists()
    assert (d / "usage.jsonl").exists()


# --- language gate: region tags and names ---


@pytest.mark.parametrize("language", ["zh-TW", "zh_Hant", "ZH", "Chinese", "english", "en-US",
                                      "Cantonese", "yue-HK"])
def test_language_tags_and_names_are_supported(tmp_path, monkeypatch, capsys, language):
    monkeypatch.setenv("AUDIO_TLDR_GLOSSARY", str(tmp_path / "none.txt"))
    d = _lang_entry(tmp_path, language, "歡迎收聽古埃。")
    _, out = _run("check", str(d), monkeypatch=monkeypatch, capsys=capsys)
    assert out["status"] == "pending"


@pytest.mark.parametrize("language", ["ja", "ja-JP", "Japanese", "ko"])
def test_other_language_tags_and_names_are_skipped(tmp_path, monkeypatch, capsys, language):
    monkeypatch.setenv("AUDIO_TLDR_GLOSSARY", str(tmp_path / "none.txt"))
    d = _lang_entry(tmp_path, language, "歡迎收聽古埃。")
    _, out = _run("check", str(d), monkeypatch=monkeypatch, capsys=capsys)
    assert out == {"status": "skip", "reason": "unsupported_language"}


def test_ollama_correction_records_summed_token_counts(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("AUDIO_TLDR_GLOSSARY", str(tmp_path / "none.txt"))
    d = _entry(tmp_path, "歡迎收聽古埃,我是盛夢公。" + "。" * 7000)
    replies = iter([("[]", 100, 2), (EDITS, 80, 30)])  # two chunks

    def chat(h, m, msgs, usage=None, **kw):
        reply, i, o = next(replies)
        usage["input"] = usage.get("input", 0) + i
        usage["output"] = usage.get("output", 0) + o
        return reply
    monkeypatch.setattr(co.digest, "call_ollama_chat", chat)
    rc, out = _run("ollama", str(d), "--model", "qwen3", monkeypatch=monkeypatch, capsys=capsys)
    assert rc == 0 and out["accepted"] == 1
    row = json.loads((d / "usage.jsonl").read_text(encoding="utf-8"))
    assert (row["phase"], row["path"], row["model"], row["input"], row["output"]) == \
        ("correct", "ollama", "qwen3", 180, 32)


def test_ollama_correction_records_usage_even_without_an_edit_list(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("AUDIO_TLDR_GLOSSARY", str(tmp_path / "none.txt"))
    d = _entry(tmp_path)

    def chat(h, m, msgs, usage=None, **kw):
        usage.update(input=10, output=5)
        return "sorry, no list"
    monkeypatch.setattr(co.digest, "call_ollama_chat", chat)
    rc, out = _run("ollama", str(d), "--model", "m", monkeypatch=monkeypatch, capsys=capsys)
    assert out == {"corrected_path": None, "reason": "no_edit_list"}
    assert json.loads((d / "usage.jsonl").read_text(encoding="utf-8"))["input"] == 10


@pytest.fixture(autouse=True)
def _no_api_show(monkeypatch):
    co.digest._NUM_CTX_CACHE.clear()
    monkeypatch.setattr(co.digest, "_model_context_length", lambda host, model: None)


def test_chunks_cut_on_line_boundaries_with_one_line_overlap():
    text = "\n".join(f"第{i}句。" + "字" * 100 for i in range(200))
    parts = co.chunks(text)
    assert all(p.split("\n")[0].startswith("第") for p in parts)
    assert parts[1].split("\n")[0] == parts[0].split("\n")[-1]


def test_ollama_correction_uses_the_shared_num_ctx(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("AUDIO_TLDR_GLOSSARY", str(tmp_path / "none.txt"))
    d = _entry(tmp_path)
    monkeypatch.setattr(co.digest, "ollama_num_ctx", lambda host, model: 12345)
    seen = {}

    def chat(h, m, msgs, options=None, usage=None, **kw):
        seen["options"] = options
        return "[]"
    monkeypatch.setattr(co.digest, "call_ollama_chat", chat)
    _run("ollama", str(d), "--model", "m", monkeypatch=monkeypatch, capsys=capsys)
    assert seen["options"]["num_ctx"] == 12345


def test_subtitle_correction_is_the_same_for_a_wrapped_transcript(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("AUDIO_TLDR_GLOSSARY", str(tmp_path / "none.txt"))
    results = []
    for name, text in (("single", "歡迎收聽古埃,我是盛夢公。今天聊投資。"),
                       ("wrapped", "歡迎收聽古埃,我是盛夢公。\n今天聊投資。")):
        d = tmp_path / name
        d.mkdir()
        (d / "transcript.txt").write_text(text, encoding="utf-8")
        (d / "transcript.srt").write_text("1\n00:00:01,000 --> 00:00:02,000\n歡迎收聽古埃,我是盛夢公。\n\n"
                                          "2\n00:00:02,000 --> 00:00:03,000\n今天聊投資。\n", encoding="utf-8")
        (d / "meta.json").write_text(json.dumps({"transcript_path": str(d / "transcript.txt"),
                                                 "srt_path": str(d / "transcript.srt")}))
        _run("apply", str(d), "--edits", "-", "--model", "m", stdin=EDITS, monkeypatch=monkeypatch, capsys=capsys)
        rc, out = _run("subtitle", str(d), "--format", "srt", monkeypatch=monkeypatch, capsys=capsys)
        results.append((rc, out["applied"], Path(out["subtitle_path"]).read_text(encoding="utf-8")))
    assert results[0] == results[1]


# ── Interpreter: find the Python that has the sound checkers ─────────
# transcribe.py switches to the interpreter that has the whisper backend; the
# README tells users to install pypinyin/jellyfish there. correct.py has to
# follow, or a user who installed them still gets checker_unavailable forever
# (2026-10-11 macOS real-path run: python3 = Homebrew 3.14, backend in 3.12).

def _interp(monkeypatch, current, others):
    """current: checkers importable here; others: {path: count}."""
    monkeypatch.delenv("AUDIO_TLDR_REEXECED", raising=False)
    monkeypatch.setattr(co.phonetic, "available",
                        lambda: {"zh": current >= 1, "en": current >= 2})
    monkeypatch.setattr(co.transcribe, "_candidate_interpreters", lambda: list(others))
    monkeypatch.setattr(co, "_checkers_in", lambda p: others[p])
    calls = []

    def fake_execv(path, argv):
        calls.append((path, argv))
        raise RuntimeError("execv")
    monkeypatch.setattr(co.os, "execv", fake_execv)
    return calls


def test_switches_to_the_interpreter_that_has_the_checkers(monkeypatch, capsys):
    calls = _interp(monkeypatch, 0, {"/fake/py314": 0, "/fake/py312": 2})
    with pytest.raises(RuntimeError):
        co._find_checker_python(["check", "/e"])
    assert calls[0][0] == "/fake/py312"
    assert calls[0][1][-2:] == ["check", "/e"]
    assert co.os.environ["AUDIO_TLDR_REEXECED"] == "1"
    assert "/fake/py312" in capsys.readouterr().err


def test_stays_when_the_current_interpreter_has_both(monkeypatch):
    calls = _interp(monkeypatch, 2, {"/fake/py312": 2})
    co._find_checker_python(["check", "/e"])
    assert calls == []


def test_switches_only_for_more_checkers_not_the_same(monkeypatch):
    calls = _interp(monkeypatch, 1, {"/fake/a": 1})
    co._find_checker_python(["check", "/e"])
    assert calls == []
    calls = _interp(monkeypatch, 1, {"/fake/a": 1, "/fake/b": 2})
    with pytest.raises(RuntimeError):
        co._find_checker_python(["check", "/e"])
    assert calls[0][0] == "/fake/b"


def test_stays_when_no_interpreter_has_them(monkeypatch):
    calls = _interp(monkeypatch, 0, {"/fake/a": 0})
    co._find_checker_python(["check", "/e"])
    assert calls == []


def test_loop_guard_stops_a_second_switch(monkeypatch):
    calls = _interp(monkeypatch, 0, {"/fake/a": 2})
    monkeypatch.setenv("AUDIO_TLDR_REEXECED", "1")
    co._find_checker_python(["check", "/e"])
    assert calls == []


def test_usage_never_switches(monkeypatch):
    """usage only appends numbers to a log; it needs no checker."""
    calls = _interp(monkeypatch, 0, {"/fake/a": 2})
    co._find_checker_python(["usage", "/e", "--json", "{}"])
    assert calls == []


def test_the_script_entry_runs_the_switch_before_main(monkeypatch):
    """The real command is `python3 correct.py check ...`: the switch must be on
    that path, not only in a helper nothing calls."""
    calls = _interp(monkeypatch, 0, {"/fake/a": 2})
    monkeypatch.setattr(co, "main", lambda argv=None: pytest.fail("main ran before the switch"))
    with pytest.raises(RuntimeError):
        co._entry(["check", "/e"])
    assert calls[0][0] == "/fake/a"


def test_checkers_in_counts_a_real_interpreter():
    n = co._checkers_in(sys.executable)
    assert n == sum(co.phonetic.available().values())
    assert co._checkers_in("/no/such/python") == 0


def test_package_versions_name_jellyfish_too():
    """jellyfish 1.x has no __version__; corrections.json recorded "unknown"
    (2026-10-11 macOS real-path run)."""
    from importlib import metadata
    v = co._package_versions()
    for mod in ("pypinyin", "jellyfish"):
        if importlib.util.find_spec(mod) is None:
            assert v[mod] is None
        else:
            assert v[mod] == metadata.version(mod)


def test_checker_switch_uses_the_shared_reexec(monkeypatch):
    """correct.py must not call os.execv itself: on Windows that leaves the caller
    with empty output (see transcribe._reexec_into)."""
    _interp(monkeypatch, 0, {"/fake/a": 2})
    seen = []
    monkeypatch.setattr(co.transcribe, "_reexec_into",
                        lambda py, script, argv: seen.append((py, script, list(argv))) or (_ for _ in ()).throw(SystemExit(0)))
    with pytest.raises(SystemExit):
        co._find_checker_python(["check", "/e"])
    assert seen and seen[0][0] == "/fake/a" and seen[0][1].endswith("correct.py") and seen[0][2] == ["check", "/e"]


# ── Windows line endings ─────────────────────────────────────────────
# On Windows transcribe.py writes transcript.txt in text mode, so it is CRLF;
# correct.py reads it as bytes (the \r\n stay in memory). Writing the corrected
# copy in text mode without newline="" turned every \r\n into \r\r\n, the file's
# hash no longer matched corrected_sha256, and check stayed "pending" forever
# (2026-10-11 Windows real-path run, Claude Code and Codex alike). The emulation
# below does what Windows text mode does, so the regression fails on any OS.

def _windows_text_mode(monkeypatch):
    real = co.transcribe._atomic_write_text

    def emulate(path, text, mtime_ns=None, newline=None):
        if newline is None:
            text = text.replace("\n", "\r\n")
        return real(path, text, mtime_ns=mtime_ns, newline="")
    monkeypatch.setattr(co.transcribe, "_atomic_write_text", emulate)


def test_crlf_transcript_apply_then_cached(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("AUDIO_TLDR_GLOSSARY", str(tmp_path / "none.txt"))
    _windows_text_mode(monkeypatch)
    d = _entry(tmp_path)
    (d / "transcript.txt").write_bytes("歡迎收聽古埃,\r\n我是盛夢公。\r\n".encode("utf-8"))
    rc, out = _run("check", str(d), monkeypatch=monkeypatch, capsys=capsys)
    assert out["status"] == "pending"
    edits = json.dumps([E("古埃", "股癌", "收聽", ",")])
    rc, out = _run("apply", str(d), "--edits", "-", "--model", "sonnet", stdin=edits,
                   monkeypatch=monkeypatch, capsys=capsys)
    assert out["accepted"] == 1
    assert b"\r\r\n" not in Path(out["corrected_path"]).read_bytes()
    rc, out = _run("check", str(d), monkeypatch=monkeypatch, capsys=capsys)
    assert out["status"] == "cached"


def test_crlf_subtitle_keeps_its_line_endings(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("AUDIO_TLDR_GLOSSARY", str(tmp_path / "none.txt"))
    _windows_text_mode(monkeypatch)
    d = _entry(tmp_path)
    (d / "transcript.srt").write_bytes(SRT.replace("\n", "\r\n").encode("utf-8"))
    _run("apply", str(d), "--edits", "-", "--model", "sonnet", stdin=EDITS, monkeypatch=monkeypatch, capsys=capsys)
    rc, out = _run("subtitle", str(d), "--format", "srt", monkeypatch=monkeypatch, capsys=capsys)
    assert out["applied"] == 1
    data = Path(out["subtitle_path"]).read_bytes()
    assert b"\r\r\n" not in data and b"\r\n" in data
