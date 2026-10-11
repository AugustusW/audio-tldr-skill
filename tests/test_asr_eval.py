"""asr_eval: every metric is checked against hand-computed answers first."""
import json
import time
from pathlib import Path

import pytest

from scripts import asr_eval as ev


class StubConv:
    """Character-level s2t for the handful of characters the tests use."""
    TABLE = {"台": "臺", "后": "後", "这": "這", "个": "個", "说": "說"}

    def convert(self, s):
        return "".join(self.TABLE.get(c, c) for c in s)


CONV = StubConv()


def test_normalize_strips_punctuation_space_width_and_case():
    assert ev.normalize("Ｈｅｌｌｏ， World！ 你好。") == "helloworld你好"


def test_normalize_converts_per_character_only():
    assert ev.normalize("这个说", CONV) == "這個說"


def test_normalize_folds_characters_speech_cannot_tell_apart():
    # same sound, and either spelling is standard: the reference cannot say
    # which one the speaker meant, so neither choice is a recognition error
    assert ev.normalize("她妳它牠祂", CONV) == ev.normalize("他你他他他", CONV)
    assert ev.normalize("裏着週嘗", CONV) == ev.normalize("裡著周嚐", CONV)
    assert ev.normalize("臺", CONV) == ev.normalize("台", CONV)


def test_normalize_drops_written_out_laughter():
    # laughter is not content: writing it out or leaving it out is not an error
    assert ev.normalize("好笑哈哈哈哈對啊", CONV) == ev.normalize("好笑對啊", CONV)
    assert ev.normalize("哈哈,沒有啦", CONV) == ev.normalize("沒有啦", CONV)


def test_normalize_drops_hesitation_sounds():
    # 呃 and 嗯 are hesitation, not content; backends write them out unevenly
    assert ev.normalize("呃,我覺得嗯就是", CONV) == ev.normalize("我覺得就是", CONV)


def test_normalize_keeps_a_single_ha_inside_words():
    assert ev.normalize("哈佛跟哈密瓜", CONV) == "哈佛跟哈密瓜"


def test_normalize_keeps_characters_that_sound_different():
    # a real misrecognition must still count: 正吉 vs 正脊, 在 vs 再
    assert ev.normalize("正吉", CONV) != ev.normalize("正脊", CONV)
    assert ev.normalize("在", CONV) != ev.normalize("再", CONV)


def test_parse_reference_marks_names_in_normalized_offsets():
    text, names = ev.parse_reference("今天〔真真〕要去〔五反田|五坂田〕。", CONV)
    assert text == "今天真真要去五反田"
    assert names == [("真真", 2, 4), ("五反田", 6, 9)]


@pytest.mark.parametrize("ref,hyp,edits", [
    ("abc", "abc", 0),
    ("abc", "xyz", 3),
    ("abc", "abxc", 1),
    ("abc", "ac", 1),
    ("", "ab", 2),
    ("台積電nvidia", "台積店nvidea", 2),
])
def test_edit_count_hand_computed(ref, hyp, edits):
    assert ev.edit_count(ev.align(ref, hyp)) == edits


def test_align_ops_are_consistent():
    ops = ev.align("abc", "abxc")
    assert [op for op, _, _ in ops] == ["eq", "eq", "ins", "eq"]
    assert ops[2] == ("ins", None, 2)


def test_cer():
    assert ev.cer("abcd", "abxd") == 0.25
    assert ev.cer("", "") == 0.0


def test_align_3000_chars_in_reasonable_time():
    ref = "台積電輝達" * 600
    hyp = ref[:1500] + "多出來的字" + ref[1500:]
    t0 = time.monotonic()
    assert ev.edit_count(ev.align(ref, hyp)) == 5
    assert time.monotonic() - t0 < 60


def _score_names(ref_raw, hyp_raw):
    ref, names = ev.parse_reference(ref_raw)
    hyp = ev.normalize(hyp_raw)
    ops = ev.align(ref, hyp)
    return ev.name_hits(names, ops), ev.name_false_positives(names, hyp, ops)


def test_name_hit_requires_every_character_in_place():
    hits, fp = _score_names("今天〔真真〕去〔五反田〕", "今天珍珍去五反田")
    assert hits == [("真真", False), ("五反田", True)] and fp == []


def test_name_with_an_insertion_inside_is_a_miss():
    hits, _ = _score_names("去〔五反田〕玩", "去五x反田玩")
    assert hits == [("五反田", False)]


def test_name_appearing_where_the_reference_has_none_is_a_false_positive():
    hits, fp = _score_names("今天〔真真〕去公園散步", "今天真真去公園真真散步")
    assert hits == [("真真", True)] and fp == [("真真", 7)]


def test_unmarked_occurrence_in_the_reference_counts_as_false_positive():
    """Documented rule: mark every occurrence. An unmarked one in the reference
    makes the matching transcript text a false positive."""
    _, fp = _score_names("〔真真〕說真真很好", "真真說真真很好")
    assert fp == [("真真", 3)]


def test_adjacent_marked_names_do_not_make_an_overlap_false_positive():
    hits, fp = _score_names("〔真真〕〔真真〕", "真真真真")
    assert hits == [("真真", True), ("真真", True)] and fp == []


def test_overlap_with_a_hit_is_not_counted_twice():
    _, fp = _score_names("〔真真〕真真", "真真真真")
    assert fp == [("真真", 2)]


# --- hallucination, repetition, script, metric matrix -------------------------

REF = "今天〔真真〕要帶大家去〔五反田〕吃一家很有名的拉麵店然後我們再去附近的公園散步看看風景"


def _res(text):
    return {"raw_text": text, "text": text, "display_segments": None}


def _post(text):
    return ev.score_sample(REF, _res(text), None)


def test_untouched_reference_scores_clean():
    s = ev.score_sample(REF, _res(ev.plain_reference(REF)), None)
    assert s["post"]["cer"] == 0 and s["post"]["name_recall"] == 1.0
    assert s["post"]["name_false_positives"] == 0 and s["post"]["hallucinations"] == []
    assert s["raw"]["repeats"] == 0


BASE = ev.plain_reference(REF)
CLEAN = _post(BASE)


@pytest.mark.parametrize("label,text,expect", [
    ("drop a name", BASE.replace("真真", "", 1),
     {"cer": "up", "name_recall": "down", "fp": "same", "hallu": "same", "repeats": "same"}),
    ("insert a sentence", BASE.replace("然後", "這段話在原本的錄音裡完全不存在然後", 1),
     {"cer": "up", "name_recall": "same", "fp": "same", "hallu": "+1", "repeats": "same"}),
    ("repeat a sentence three times", BASE.replace("然後", "很有名的拉麵店很有名的拉麵店然後", 1),
     {"cer": "up", "name_recall": "same", "fp": "same", "hallu": "same", "repeats": "+1"}),
    ("put a name somewhere else", BASE.replace("公園", "公園真真", 1),
     {"cer": "up", "name_recall": "same", "fp": "+1", "hallu": "same", "repeats": "same"}),
])
def test_metric_matrix(label, text, expect):
    s = ev.score_sample(REF, _res(text), None)
    raw, base = s["raw"], CLEAN["raw"]
    got = {
        "cer": "up" if raw["cer"] > base["cer"] else "same",
        "name_recall": "down" if raw["name_recall"] < base["name_recall"] else "same",
        "fp": "+1" if raw["name_false_positives"] == base["name_false_positives"] + 1 else "same",
        "hallu": "+1" if len(raw["hallucinations"]) == len(base["hallucinations"]) + 1 else "same",
        "repeats": "+1" if raw["repeats"] == base["repeats"] + 1 else "same",
    }
    assert got == expect, label


def test_repeats_measured_on_raw_and_collapse_recorded_on_post():
    raw = BASE.replace("然後", "很有名的拉麵店很有名的拉麵店然後", 1)
    res = {"raw_text": raw, "text": transcribe_collapse(raw), "display_segments": None}
    s = ev.score_sample(REF, res, None)
    assert s["raw"]["repeats"] == 1 and s["post"]["collapsed_chars"] > 0


def transcribe_collapse(text):
    return ev.transcribe._collapse_repetitions(text)


def test_simplified_count_skips_ambiguous_characters():
    assert ev.simplified_count("这个说干", CONV) == 3  # 干 is valid Traditional too


def test_srt_path_scored_when_segments_exist():
    res = {"raw_text": BASE, "text": BASE,
           "display_segments": [{"start": 0, "end": 1, "text": BASE}]}
    assert ev.score_sample(REF, res, None)["srt"]["cer"] == 0


def _make_sample(base, sid="s1", text="今天〔真真〕去公園散步看看風景"):
    d = base / sid
    d.mkdir(parents=True)
    (d / "sample.json").write_text(json.dumps({"id": sid, "language": "zh", "kind": "test"}))
    (d / "reference.txt").write_text(text, encoding="utf-8")
    (d / "clip.mp3").write_bytes(b"fake")
    return d


def test_run_pipeline_end_to_end_with_a_stub_backend(tmp_path, monkeypatch, capsys):
    _make_sample(tmp_path / "public")
    monkeypatch.setattr(ev, "PUBLIC_DIR", tmp_path / "public")
    monkeypatch.setattr(ev, "PRIVATE_DIR", tmp_path / "nope")
    monkeypatch.setattr(ev, "char_converter", lambda: CONV)
    calls = []
    def stub(path, backend, language=None, model=None, want_segments=False, **options):
        calls.append((backend, model, options))
        text = "今天珍珍去公園散步看看風景"
        return {"raw_text": text, "text": text, "display_segments": None}
    monkeypatch.setattr(ev.transcribe, "transcribe_audio", stub)
    out = tmp_path / "results"
    rc = ev.main(["run", "--samples", "all", "--backend", "mlx-whisper", "--repeat", "2",
                  "--label", "t", "--out", str(out)])
    assert rc == 0 and len(calls) == 2
    doc = json.loads(next(out.glob("*-t.json")).read_text(encoding="utf-8"))
    run0 = doc["samples"]["s1"]["runs"][0]["post"]
    assert run0["name_recall"] == 0.0
    assert doc["thresholds"]["HALLU_WINDOW"] == 10 and doc["repeat"] == 2
    assert len(doc["samples"]["s1"]["reference_sha256"]) == 64
    assert "private" in capsys.readouterr().err  # told the private set is absent


def test_acquire_clip_names_the_fields_to_fix_when_the_url_is_dead(tmp_path, monkeypatch):
    d = tmp_path / "s"
    d.mkdir()
    sample = {"id": "s", "source": "https://dead.example/x.mp3", "start": 0, "end": 60,
              "feed": "https://feed.example/rss", "episode": "EP1", "dir": d}
    def dead(url, workdir):
        raise ev.transcribe.DownloadError("HTTP 403")
    monkeypatch.setattr(ev.transcribe, "download_audio", dead)
    with pytest.raises(SystemExit) as e:
        ev.acquire_clip(sample, cache_root=tmp_path / "cache")
    assert "feed" in str(e.value) and "EP1" in str(e.value)


def _doc(per_sample, ref_sha="r"):
    """per_sample: {id: [(edits, ref_len, [[name, ok], ...], [hallucination texts], fp), ...runs]}"""
    samples = {}
    for sid, runs in per_sample.items():
        samples[sid] = {"reference_sha256": ref_sha + sid, "audio_sha256": "a", "runs": [
            {"post": {"edits": e, "ref_len": n, "cer": e / n, "names": names,
                      "hallucinations": h, "name_false_positives": fp}}
            for e, n, names, h, fp in runs]}
    return {"samples": samples}


def _same(edits):
    return {f"s{i}": [(edits, 1000, [["真真", True]], [], 0)] * 3 for i in range(6)}


def test_compare_identical_is_no_change():
    r = ev.compare_docs(_doc(_same(50)), _doc(_same(50)))
    assert r["cer_verdict"] == "inconclusive" and not r["regressed"]


def test_compare_detects_a_consistent_cer_rise():
    r = ev.compare_docs(_doc(_same(50)), _doc(_same(80)))
    assert r["cer_verdict"] == "regressed" and r["regressed"]


def test_compare_name_that_was_right_and_is_now_wrong_regresses():
    new = _same(50)
    new["s0"] = [(50, 1000, [["真真", False]], [], 0)] * 3
    r = ev.compare_docs(_doc(_same(50)), _doc(new))
    assert r["name_regressions"] == [["s0", "真真"]] and r["regressed"]


def test_compare_single_run_does_not_flag_everything_as_regressed():
    base = {f"s{i}": [(50, 1000, [], [], 0)] for i in range(6)}
    new = {f"s{i}": [(50 + (1 if i % 2 else -1), 1000, [], [], 0)] for i in range(6)}
    r = ev.compare_docs(_doc(base), _doc(new))
    assert not r["regressed"]


def test_compare_refuses_different_references():
    with pytest.raises(SystemExit):
        ev.compare_docs(_doc(_same(50), ref_sha="x"), _doc(_same(50), ref_sha="y"))


def test_compare_lists_new_hallucination_texts():
    new = _same(50)
    new["s1"] = [(50, 1000, [["真真", True]], ["謝謝收看請訂閱"], 0)] * 3
    r = ev.compare_docs(_doc(_same(50)), _doc(new))
    assert r["new_hallucination_texts"] == [["s1", "謝謝收看請訂閱"]]


def test_compare_refuses_different_audio_or_backend():
    base, new = _doc(_same(50)), _doc(_same(50))
    new["samples"]["s0"]["audio_sha256"] = "other"
    with pytest.raises(SystemExit):
        ev.compare_docs(base, new)
    with pytest.raises(SystemExit):
        ev.compare_docs({**_doc(_same(50)), "backend": "mlx-whisper"},
                        {**_doc(_same(50)), "backend": "faster-whisper"})


def test_rescore_recomputes_from_stored_texts(tmp_path, monkeypatch):
    _make_sample(tmp_path / "public")
    monkeypatch.setattr(ev, "PUBLIC_DIR", tmp_path / "public")
    monkeypatch.setattr(ev, "PRIVATE_DIR", tmp_path / "nope")
    monkeypatch.setattr(ev, "char_converter", lambda: CONV)
    text = "今天真真去公園散步看看風景"
    doc = {"label": "x", "backend": "mlx-whisper", "samples": {"s1": {
        "reference_sha256": "r", "audio_sha256": "a",
        "runs": [{"texts": {"raw": text, "post": text, "srt": None}}]}}}
    src = tmp_path / "x.json"
    src.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    assert ev.main(["rescore", str(src), "--out", str(tmp_path / "out")]) == 0
    new = json.loads(next((tmp_path / "out").glob("*-x-rescored.json")).read_text(encoding="utf-8"))
    assert new["samples"]["s1"]["runs"][0]["post"]["name_recall"] == 1.0


def test_bootstrap_is_reproducible():
    a = ev.compare_docs(_doc(_same(50)), _doc(_same(55)), seed=7)
    b = ev.compare_docs(_doc(_same(50)), _doc(_same(55)), seed=7)
    assert a["ci"] == b["ci"]


def test_rescore_records_the_reference_it_used_and_leaves_input_alone(tmp_path, monkeypatch):
    import hashlib
    d = _make_sample(tmp_path / "public")
    monkeypatch.setattr(ev, "PUBLIC_DIR", tmp_path / "public")
    monkeypatch.setattr(ev, "PRIVATE_DIR", tmp_path / "nope")
    monkeypatch.setattr(ev, "char_converter", lambda: CONV)
    text = "今天真真去公園散步看看風景"
    doc = {"label": "x", "backend": "mlx-whisper", "samples": {"s1": {
        "reference_sha256": "stale", "audio_sha256": "a",
        "runs": [{"texts": {"raw": text, "post": text, "srt": None}}]}}}
    src = tmp_path / "x.json"
    src.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    before = src.read_bytes()
    assert ev.main(["rescore", str(src), "--out", str(tmp_path / "out")]) == 0
    new = json.loads(next((tmp_path / "out").glob("*-x-rescored.json")).read_text(encoding="utf-8"))
    sha = new["samples"]["s1"]["reference_sha256"]
    assert len(sha) == 64 and sha == hashlib.sha256((d / "reference.txt").read_bytes()).hexdigest()
    assert src.read_bytes() == before


def test_compare_refuses_partial_sample_sets():
    new = _same(50)
    del new["s0"]
    with pytest.raises(SystemExit) as e:
        ev.compare_docs(_doc(_same(50)), _doc(new))
    assert "s0" in str(e.value)
    with pytest.raises(SystemExit):
        ev.compare_docs(_doc({}), _doc({}))


def test_compare_srt_without_segments_exits_cleanly():
    d = _doc(_same(50))
    for s in d["samples"].values():
        for r in s["runs"]:
            r["srt"] = None
    with pytest.raises(SystemExit) as e:
        ev.compare_docs(d, d, path="srt")
    assert "srt" in str(e.value)


def test_disagreements_group_differences_and_carry_timestamps():
    a = "今天珍珍要去五反田吃拉麵"
    b = "今天真真要去五反田吃拉麵"
    segs = [{"start": 65.0, "end": 70.0, "text": a}]
    out = ev.disagreements(a, b, segs)
    assert out == [{"at": "01:05", "a": "珍珍", "b": "真真"}]


def test_draft_never_overwrites_the_reference(tmp_path, monkeypatch):
    d = _make_sample(tmp_path / "public", text="已校對")
    monkeypatch.setattr(ev, "PUBLIC_DIR", tmp_path / "public")
    monkeypatch.setattr(ev, "PRIVATE_DIR", tmp_path / "nope")
    monkeypatch.setattr(ev.transcribe, "detect_backend", lambda: "mlx-whisper")
    def stub(path, backend, language=None, model=None, want_segments=False, **o):
        t = "版本B" if model else "版本A"
        return {"raw_text": t, "text": t,
                "display_segments": [{"start": 0.0, "end": 1.0, "text": t}]}
    monkeypatch.setattr(ev.transcribe, "transcribe_audio", stub)
    assert ev.main(["draft", "s1"]) == 0
    assert (d / "reference.txt").read_text(encoding="utf-8") == "已校對"
    assert (d / "reference.draft.txt").read_text(encoding="utf-8").strip() == "版本A"
    assert "A「a」 B「b」" in (d / "disagreements.md").read_text(encoding="utf-8")  # normalized text


def test_disagreements_offsets_skip_punctuation_in_segments():
    segs = [{"start": 0, "end": 5, "text": "今天，真真"},
            {"start": 3700, "end": 3705, "text": "要去五反田。"}]
    a = "".join(s["text"] for s in segs)
    b = a.replace("五反田", "五坂田")
    out = ev.disagreements(a, b, segs)
    assert [r["at"] for r in out] == ["61:40"]


def test_disagreements_pure_insertion_uses_running_position():
    segs = [{"start": 0, "end": 5, "text": "今天"},
            {"start": 3700, "end": 3705, "text": "要去"}]
    out = ev.disagreements("今天要去", "今天要去很", segs)
    assert out == [{"at": "61:40", "a": "", "b": "很"}]


def test_draft_stamps_regions_from_display_segments_not_collapsed_text(tmp_path, monkeypatch):
    d = _make_sample(tmp_path / "public", text="已校對")
    monkeypatch.setattr(ev, "PUBLIC_DIR", tmp_path / "public")
    monkeypatch.setattr(ev, "PRIVATE_DIR", tmp_path / "nope")
    monkeypatch.setattr(ev.transcribe, "detect_backend", lambda: "mlx-whisper")
    segs_a = [{"start": 0.0, "end": 1.0, "text": "哈哈哈哈哈哈哈哈哈哈哈哈"},
              {"start": 3700.0, "end": 3701.0, "text": "珍珍來了"}]
    segs_b = [{"start": 0.0, "end": 1.0, "text": "哈哈哈哈哈哈哈哈哈哈哈哈"},
              {"start": 3700.0, "end": 3701.0, "text": "真真來了"}]
    def stub(path, backend, language=None, model=None, want_segments=False, **o):
        segs = segs_b if model else segs_a
        return {"raw_text": "x", "text": "哈珍珍來了" if not model else "哈真真來了",
                "display_segments": segs}
    monkeypatch.setattr(ev.transcribe, "transcribe_audio", stub)
    assert ev.main(["draft", "s1"]) == 0
    assert "[61:40] A「珍珍」 B「真真」" in (d / "disagreements.md").read_text(encoding="utf-8")


NEEDLES = [{"sentence": "順帶一提，幻星科技的新耳機定價四二八〇元。", "keys": ["幻星科技", "4280"]},
           {"sentence": "另外，青嵐咖啡在週三公休。", "keys": ["青嵐咖啡", "週三"]}]


def test_build_longdoc_puts_every_needle_in_the_last_third():
    texts = ["甲。" * 300, "乙。" * 300, "丙。" * 300]
    doc, positions = ev.build_longdoc(texts, NEEDLES, seed=1)
    assert all(n["sentence"] in doc for n in NEEDLES)
    assert all(p >= len(doc) * 0.6 for p in positions)


def test_needle_recall_needs_every_key():
    summary = "重點：幻星科技新耳機 4280 元；青嵐咖啡營業時間未提。"
    assert ev.needle_recall(summary, NEEDLES) == 1


def test_needles_fixture_is_well_formed():
    needles = json.loads((ev.PUBLIC_DIR / "needles.json").read_text(encoding="utf-8"))
    assert len(needles) == 5 and all(n["keys"] for n in needles)


def test_public_samples_are_complete_and_small():
    samples = [s for s in ev.load_samples("public")]
    assert {s["id"] for s in samples} == {"aow-zh", "canterville-en", "music-silence"}
    for s in samples:
        assert (s["dir"] / "reference.txt").read_text(encoding="utf-8").strip()
        assert (s["dir"] / "clip.mp3").stat().st_size < 1_000_000
        assert "public domain" in (s["dir"] / "LICENSE.txt").read_text(encoding="utf-8").lower()


# --- final-review fixes ---------------------------------------------------------


def _docx(per_sample, extra_post=None, raw=None, **top):
    d = _doc(per_sample)
    for sid, s in d["samples"].items():
        for k, r in enumerate(s["runs"]):
            r["post"].update((extra_post or {}).get(sid, {}))
            if raw and sid in raw:
                r["raw"] = dict(raw[sid])
    d.update(top)
    return d


def test_compare_one_sample_regressing_five_to_forty_percent_is_regressed():
    new = _same(50)
    new["s0"] = [(400, 1000, [["真真", True]], [], 0)] * 3
    r = ev.compare_docs(_doc(_same(50)), _doc(new))
    assert r["regressed"]
    assert any("s0" in reason for reason in r["reasons"])


def test_compare_hallucination_total_rising_alone_is_regressed():
    new = _same(50)
    new["s2"] = [(50, 1000, [["真真", True]], ["a", "b", "c"], 0)] * 3
    r = ev.compare_docs(_doc(_same(50)), _doc(new))
    assert r["regressed"] and r["cer_verdict"] != "regressed"
    assert any("hallucination" in reason for reason in r["reasons"])


def test_compare_name_false_positive_total_rising_is_regressed():
    new = _same(50)
    new["s2"] = [(50, 1000, [["真真", True]], [], 2)] * 3
    r = ev.compare_docs(_doc(_same(50)), _doc(new))
    assert r["regressed"] and any("false positive" in x for x in r["reasons"])


def test_compare_improvement_everywhere_is_improved_not_regressed():
    r = ev.compare_docs(_doc(_same(80)), _doc(_same(50)))
    assert r["cer_verdict"] == "improved" and not r["regressed"] and r["reasons"] == []


def test_compare_single_run_per_sample_flags_never_regress():
    base = {f"s{i}": [(50, 1000, [], [], 0)] for i in range(6)}
    new = dict(base)
    new["s0"] = [(400, 1000, [], [], 0)]
    r = ev.compare_docs(_doc(base), _doc(new))
    assert any(f[0] == "s0" for f in r["flagged_samples"])
    assert r["worse_samples"] == []


def test_compare_bootstrap_with_varied_sample_cers_has_a_real_interval():
    base = {f"s{i}": [(20 + 15 * i, 1000, [], [], 0)] * 3 for i in range(6)}
    new = {f"s{i}": [(20 + 15 * i + (30 if i < 4 else -5), 1000, [], [], 0)] * 3
           for i in range(6)}
    r = ev.compare_docs(_doc(base), _doc(new))
    lo, hi = r["ci"]
    assert lo < hi and hi > 0 and lo < r["pooled_cer"][1] - r["pooled_cer"][0] < hi


def test_compare_reports_the_minimum_sample_delta():
    r = ev.compare_docs(_doc(_same(50)), _doc(_same(50)))
    assert r["min_sample_delta"] == ev.MIN_SAMPLE_DELTA == 0.01


def test_compare_sees_repeats_simplified_and_collapsed_chars():
    raw0 = {f"s{i}": {"repeats": 0, "simplified_chars": 0} for i in range(6)}
    raw1 = {**raw0, "s3": {"repeats": 2, "simplified_chars": 0}}
    raw2 = {**raw0, "s4": {"repeats": 0, "simplified_chars": 7}}
    zero = {f"s{i}": {"collapsed_chars": 0} for i in range(6)}
    col = {**zero, "s1": {"collapsed_chars": 12}}
    base = _docx(_same(50), raw=raw0, extra_post=zero)
    r = ev.compare_docs(base, _docx(_same(50), raw=raw1, extra_post=col))
    assert r["repeats"] == [0, 2] and r["collapsed_chars"] == [0, 12]
    assert r["regressed"] and any("repeat" in x and "s3" in x for x in r["reasons"])
    r = ev.compare_docs(base, _docx(_same(50), raw=raw2, extra_post=zero))
    assert r["simplified_chars"] == [0, 7]
    assert r["regressed"] and any("simplified" in x for x in r["reasons"])


def test_compare_refuses_different_thresholds():
    a = _docx(_same(50), thresholds={"HALLU_WINDOW": 10, "HALLU_MATCH": 0.6})
    b = _docx(_same(50), thresholds={"HALLU_WINDOW": 10, "HALLU_MATCH": 0.5})
    with pytest.raises(SystemExit) as e:
        ev.compare_docs(a, b)
    assert "HALLU_MATCH" in str(e.value)


def test_compare_refuses_different_env():
    a = _docx(_same(50), env={"AUDIO_TLDR_DEREPEAT": None, "AUDIO_TLDR_MODEL": "x"})
    b = _docx(_same(50), env={"AUDIO_TLDR_DEREPEAT": "off", "AUDIO_TLDR_MODEL": "x"})
    with pytest.raises(SystemExit) as e:
        ev.compare_docs(a, b)
    assert "AUDIO_TLDR_DEREPEAT" in str(e.value) and "AUDIO_TLDR_MODEL" not in str(e.value)


def test_metrics_do_not_depend_on_audio_tldr_derepeat(monkeypatch):
    raw = BASE.replace("然後", "很有名的拉麵店很有名的拉麵店很有名的拉麵店然後", 1)
    res = {"raw_text": raw, "text": raw, "display_segments": None}
    want = ev.score_sample(REF, res, None)
    monkeypatch.setenv("AUDIO_TLDR_DEREPEAT", "off")
    got = ev.score_sample(REF, res, None)
    assert got["post"]["hallucinations"] == want["post"]["hallucinations"]
    assert got["post"]["collapsed_chars"] == want["post"]["collapsed_chars"] > 0


def test_result_doc_records_env_and_whisper_cpp_model(monkeypatch):
    for k in ev.ENV_KEYS:
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("AUDIO_TLDR_WHISPER_CPP_MODEL", "/m/ggml.bin")
    monkeypatch.setenv("AUDIO_TLDR_DEREPEAT", "off")
    d = ev.result_doc("l", "whisper-cpp", None, {}, 1, {})
    assert d["env"]["AUDIO_TLDR_DEREPEAT"] == "off" and d["env"]["AUDIO_TLDR_MODEL"] is None
    assert d["model"] == "/m/ggml.bin"
    assert d["thresholds"]["MIN_SAMPLE_DELTA"] == 0.01


def test_pre_collapse_keeps_a_tripled_phrase_from_counting_as_hallucination():
    chars = "".join(chr(0x4E00 + i) for i in range(220))   # 220 distinct characters
    head, phrase, tail = chars[:60], chars[60:160], chars[160:]
    ref = head + phrase + tail
    raw = head + phrase * 3 + tail                           # the phrase is said three times
    s = ev.score_sample(ref, {"raw_text": raw, "text": raw, "display_segments": None}, None)
    assert s["post"]["hallucinations"] == []
    hyp = ev.normalize(raw)  # without the pre-collapse the extra copies are hallucinations
    assert ev.hallucinated_spans(ref, hyp, ev.align(ref, hyp))


def test_run_defaults_to_private_samples_and_draft_needs_a_backend(tmp_path, monkeypatch):
    seen = []
    monkeypatch.setattr(ev, "char_converter", lambda: CONV)
    monkeypatch.setattr(ev.transcribe, "detect_backend", lambda: None)
    monkeypatch.setattr(ev, "load_samples", lambda which: seen.append(which) or [{"id": "s1", "dir": tmp_path}])
    with pytest.raises(SystemExit) as e:
        ev.main(["run"])
    assert "no whisper backend" in str(e.value)
    with pytest.raises(SystemExit) as e:
        ev.main(["draft", "s1"])
    assert "no whisper backend" in str(e.value)
    monkeypatch.setattr(ev.transcribe, "detect_backend", lambda: "mlx-whisper")
    monkeypatch.setattr(ev, "run_eval", lambda *a, **k: {})
    monkeypatch.setattr(ev, "RESULTS_DIR", tmp_path / "x" / "results")
    ev.main(["run", "--out", str(tmp_path / "o")])
    assert seen[-1] == "private"


# --- correct subcommand ---------------------------------------------------------


def _fake_result(tmp_path, monkeypatch, texts, reference):
    d = _make_sample(tmp_path / "private", text=reference)
    monkeypatch.setattr(ev, "PRIVATE_DIR", tmp_path / "private")
    monkeypatch.setattr(ev, "PUBLIC_DIR", tmp_path / "nope")
    monkeypatch.setattr(ev, "char_converter", lambda: CONV)
    doc = {"label": "base", "backend": "x", "model": "m", "env": {}, "options": {}, "repeat": 1,
           "thresholds": {}, "commit": "c", "date": "d",
           "samples": {sid: {"id": sid, "runs": [{"texts": {"raw": t, "post": t, "srt": ""}}]}
                       for sid, t in texts.items()}}
    p = tmp_path / "base.json"
    p.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    return p


def test_edit_effects_marks_fix_and_break():
    ref = "歡迎收聽〔股癌〕我是〔謝孟恭〕"
    text = "歡迎收聽古埃我是謝孟恭"
    acc = [{"wrong": "古埃", "right": "股癌", "spans": [[4, 6]], "count": 1},
           {"wrong": "謝孟恭", "right": "盛夢公", "spans": [[8, 11]], "count": 1}]
    eff = ev.edit_effects(ref, text, acc, CONV)
    assert [e["delta"] < 0 for e in eff] == [True, False]


def test_correct_with_claude_builds_a_toolless_call(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-secret")
    calls = []

    class P:
        returncode, stdout, stderr = 0, json.dumps({"result": "[]", "usage": {}}), ""

    def runner(argv, **kw):
        calls.append((argv, kw))
        return P()
    out = ev.correct_with_provider("claude", "逐字稿", "ref", runner=runner)
    argv, kw = calls[0]
    assert out == "[]" and argv[:2] == ["claude", "-p"] and "--disallowedTools" in argv
    assert "逐字稿" in kw["input"] and "逐字稿" not in " ".join(argv)
    assert "ANTHROPIC_API_KEY" not in kw["env"]
    i = argv.index("--tools")
    assert argv[i + 1] == ""
    assert argv[argv.index("--settings") + 1] == ev.CLAUDE_SETTINGS
    assert argv[argv.index("--mcp-config") + 1] == '{"mcpServers":{}}' and "--strict-mcp-config" in argv
    assert "--no-session-persistence" in argv
    deny = argv[argv.index("--disallowedTools") + 1].split(",")
    assert {"Bash", "Write", "Read", "Grep", "Glob", "WebFetch", "Skill", "KillShell"} <= set(deny)
    assert kw["cwd"] and not str(kw["cwd"]).startswith(str(ev.ROOT))


def test_correct_with_ollama_uses_the_shipped_call_shape(monkeypatch):
    dg = ev.correct.digest
    seen = {}

    def chat(host, model, messages, timeout=None, options=None, truncate=None):
        seen.update(model=model, options=options, truncate=truncate)
        return '[{"wrong":"a","right":"b","scope":"all"}]'
    monkeypatch.setattr(dg, "call_ollama_chat", chat)
    monkeypatch.setattr(dg, "resolve_ollama_host", lambda h: "http://x")
    monkeypatch.setattr(dg, "ollama_num_ctx", lambda host, model: 32768)
    out = ev.correct_with_provider("ollama:m1", "逐字稿", "ref")
    assert seen == {"model": "m1", "options": {"num_ctx": 32768}, "truncate": False}
    assert json.loads(out)[0]["right"] == "b"


def test_cmd_correct_writes_result(tmp_path, monkeypatch):
    res = _fake_result(tmp_path, monkeypatch, texts={"s1": "歡迎收聽古埃"}, reference="歡迎收聽〔股癌〕")
    monkeypatch.setattr(ev, "correct_with_provider",
                        lambda p, t, r, runner=None, info=None: '[{"wrong":"古埃","right":"股癌","before":"收聽","after":"","scope":"once"}]')
    assert ev.main(["correct", str(res), "--provider", "claude", "--repeat", "1",
                    "--label", "t", "--out", str(tmp_path)]) == 0
    out = json.loads(sorted(tmp_path.glob("*-t.json"))[-1].read_text(encoding="utf-8"))
    run = out["samples"]["s1"]["runs"][0]
    assert run["post"]["cer"] == 0 and run["correction"]["accepted"] == 1
    assert run["correction"]["effects"][0]["delta"] < 0


CODEX_STREAM = "\n".join(json.dumps(e) for e in [
    {"type": "thread.started", "thread_id": "t"},
    {"type": "item.completed", "item": {"type": "error", "message": "Code Mode is unavailable"}},
    {"type": "item.completed", "item": {"type": "agent_message", "text": "[]"}},
    {"type": "turn.completed", "usage": {"input_tokens": 1}},
])


def _codex_runner(stdout, rc=0, calls=None):
    class P:
        returncode, stderr = rc, "boom"
    P.stdout = stdout

    def runner(argv, **kw):
        if calls is not None:
            agents = Path(kw["cwd"], "AGENTS.md")
            calls.append((argv, kw, agents.read_text(encoding="utf-8"), oct(agents.stat().st_mode & 0o777)))
        return P()
    return runner


def test_correct_with_codex_mirrors_the_hardened_call(monkeypatch):
    for k in ("OPENAI_API_KEY", "OPENAI_BASE_URL", "OPENAI_ORG_ID", "OPENAI_PROJECT_ID", "OPENAI_PROJECT"):
        monkeypatch.setenv(k, "x")
    calls = []
    out = ev.correct_with_provider("codex", "逐字稿", "ref", runner=_codex_runner(CODEX_STREAM, calls=calls))
    argv, kw, agents, mode = calls[0]
    assert out == "[]" and argv[:3] == ["codex", "exec", "--ephemeral"] and argv[-1] == "-"
    for flag in ("--ignore-user-config", "--ignore-rules", "--strict-config", "--skip-git-repo-check", "--json"):
        assert flag in argv
    disabled = [argv[i + 1] for i, a in enumerate(argv) if a == "--disable"]
    assert disabled == list(ev.CODEX_DISABLED_FEATURES)
    assert argv[argv.index("--model") + 1] == "gpt-5.6-terra"
    cfg = [argv[i + 1] for i, a in enumerate(argv) if a == "-c"]
    assert cfg == ['approval_policy="never"', 'forced_login_method="chatgpt"',
                   "agents.enabled=false", 'web_search="disabled"']
    assert argv[argv.index("-C") + 1] == kw["cwd"]
    assert "逐字稿" in kw["input"] and "逐字稿" not in " ".join(argv)
    assert mode == "0o600" and agents
    assert not any(k.startswith("OPENAI_") for k in kw["env"])


@pytest.mark.parametrize("stdout", [
    "\n".join(CODEX_STREAM.splitlines()[:-1]),                                  # no turn.completed
    CODEX_STREAM + '\n{"type":"turn.failed","error":"quota"}',
    '{"type":"turn.completed"}',                                                # no message
    "not json",
])
def test_codex_incomplete_or_failed_turn_raises(stdout):
    with pytest.raises(RuntimeError):
        ev.correct_with_provider("codex", "t", "r", runner=_codex_runner(stdout))


def test_codex_nonzero_exit_raises():
    with pytest.raises(RuntimeError, match="exit 3"):
        ev.correct_with_provider("codex", "t", "r", runner=_codex_runner("", rc=3))


def test_cmd_correct_records_parse_and_provider_errors_and_continues(tmp_path, monkeypatch):
    res = _fake_result(tmp_path, monkeypatch, texts={"s1": "歡迎收聽古埃"}, reference="歡迎收聽〔股癌〕")
    replies = iter(["這不是陣列", RuntimeError("down"),
                    '[{"wrong":"古埃","right":"股癌","before":"收聽","after":"","scope":"once"}]'])

    def fake(p, t, r, runner=None, info=None):
        v = next(replies)
        if isinstance(v, Exception):
            raise v
        return v
    monkeypatch.setattr(ev, "correct_with_provider", fake)
    assert ev.main(["correct", str(res), "--provider", "claude", "--repeat", "3",
                    "--label", "e", "--out", str(tmp_path)]) == 0
    out = json.loads(sorted(tmp_path.glob("*-e.json"))[-1].read_text(encoding="utf-8"))
    runs = out["samples"]["s1"]["runs"]
    assert runs[0]["correction"]["proposed"] is None and runs[0]["correction"]["parse_error"]
    assert "provider_error" in runs[1]["correction"] and runs[1]["correction"]["proposed"] is None
    assert runs[2]["correction"]["accepted"] == 1 and "parse_error" not in runs[2]["correction"]
    assert out["repeat"] == 3 and out["transcription_repeat"] == 1


def test_ollama_counts_chunks_without_an_array(monkeypatch):
    dg = ev.correct.digest
    replies = iter(["no array here", '[{"wrong":"a","right":"b","scope":"all"}]'])
    monkeypatch.setattr(dg, "call_ollama_chat", lambda *a, **k: next(replies))
    monkeypatch.setattr(dg, "resolve_ollama_host", lambda h: "http://x")
    monkeypatch.setattr(ev.correct, "chunks", lambda t: ["a", "b"])
    info = {}
    ev.correct_with_provider("ollama:m", "ab", "ref", info=info)
    assert info == {"chunks": 2, "chunks_unparsed": 1}
