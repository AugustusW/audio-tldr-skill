"""wrap_lines: only ever inserts line breaks (v1.0 item 5)."""
import importlib.util
import random
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "skills" / "audio-tldr" / "scripts" / "transcribe.py"
spec = importlib.util.spec_from_file_location("transcribe_wrap", SCRIPT)
tr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tr)


_ALPHABET = list("的一是在不了有和人這中大為上個國我以要他時來用們生到作地於出就分對成會可主發年動同工也能下過子說產種面而方後多定行學法所民得經十三之進着等部度家電力裡如水化高自二理起小物現實加量都兩體制機當使點從業本去把性好應開它合還因由其些然前外天政四日那社義事平形相全表間樣與關各重新線內數正心反你明看原又麼利比或但質氣第向道命此變條只沒結解問意建月公無系軍很情者最立代想已通並提直題黨程展五果料象員革位入常文總次品式活設及管特件長求老頭基資邊流路級少圖山統接知較將組見計別她手角期根論運農指幾九區強放決西被幹做必戰先回則任取據處隊南給色光門即保治北造百規熱領七海口東導器壓志世金增爭濟階油思術極交受聯什認六共權收證改清美再採轉更單風切打白教速花帶安場身車例真務具萬每目至達走積示議聲報鬥完類八離華名確才科張信馬節話米整空元況今集溫傳土許步群廣石記需段研界拉林律叫且究觀越織裝影算低持音眾書布复容兒須際商非驗連斷深難近礦千週委素技備半辦青省列習響約支般史感勞便團往酸歷市克何除消構府稱太準精值號率族維劃選標寫存候毛親快效斯院查江型眼王按格養易置派層片始卻專狀育廠京識適屬圓包火住調滿縣局照參紅細引聽該鐵價嚴龍飛" "abcABC123 ,.!?，。！？「」\r\n\t")


def _segs(*texts):
    return [{"start": i, "end": i + 1, "text": t} for i, t in enumerate(texts)]


def test_one_segment_per_line():
    text = "歡迎收聽古埃,我是盛夢公。最近台股逼近5萬點,大家常問部位怎麼配置。屁股坐哪裡,骨盆穩不穩。"
    segs = _segs("歡迎收聽古埃,我是盛夢公。", "最近台股逼近5萬點,大家常問部位怎麼配置。", "屁股坐哪裡,骨盆穩不穩。")
    assert tr.wrap_lines(text, segs).split("\n") == [s["text"] for s in segs]


def test_converted_segment_text_is_located():
    text = "这是简体。這是繁體。"  # transcript already converted for the second segment only
    segs = _segs("这是简体。", "这是繁体。")
    out = tr.wrap_lines(text, segs, convert=lambda s: s.replace("这是繁体", "這是繁體"))
    assert out == "这是简体。\n這是繁體。"


def test_one_missing_segment_does_not_break_the_rest():
    segs = _segs("第一段。", "這段在後處理被刪掉了很長很長很長很長很長很長很長很長很長很長很長很長很長很長很長。",
                 "第三段。", "第四段。")
    text = "第一段。第三段。第四段。"
    assert tr.wrap_lines(text, segs) == "第一段。\n第三段。\n第四段。"


def test_long_unpunctuated_chinese_breaks_at_400_or_earlier():
    text = "嗯" * 1000
    lines = tr.wrap_lines(text).split("\n")
    assert all(len(l) <= tr.LINE_MAX for l in lines) and "".join(lines) == text


def test_long_line_prefers_sentence_end_after_200():
    text = "甲" * 250 + "。" + "乙" * 300
    lines = tr.wrap_lines(text).split("\n")
    assert lines[0] == "甲" * 250 + "。"


def test_closing_quote_stays_with_the_sentence():
    text = "甲" * 250 + "。」" + "乙" * 300
    assert tr.wrap_lines(text).split("\n")[0].endswith("。」")


def test_never_cuts_inside_an_ascii_word():
    text = "甲" * 390 + "ChatGPTClaudeGemini" + "乙" * 300
    lines = tr.wrap_lines(text).split("\n")
    assert any("ChatGPTClaudeGemini" in l for l in lines)  # the word sits whole on one line
    assert "".join(lines) == text


def test_all_ascii_run_longer_than_400_is_still_cut():
    url = "https://example.com/" + "a" * 600
    lines = tr.wrap_lines(url).split("\n")
    assert all(len(l) <= tr.LINE_MAX for l in lines) and "".join(lines) == url


def test_crlf_is_never_split_and_existing_breaks_are_kept():
    text = "第一行\r\n" + "嗯" * 900
    out = tr.wrap_lines(text)
    assert "\r\n" in out and "\r\r" not in out
    assert all(out[i + 1] == "\n" for i, c in enumerate(out) if c == "\r")  # every \r still ends a line
    assert tr.strip_breaks(out) == tr.strip_breaks(text)


def test_short_or_empty_text():
    assert tr.wrap_lines("") == ""
    assert tr.wrap_lines("只有一句。", _segs("只有一句。")) == "只有一句。"
    assert "\n\n" not in tr.wrap_lines("一。二。", _segs("一。", "二。"))


def test_already_wrapped_text_is_unchanged():
    text = "一段一行。\n第二行。\n"
    assert tr.wrap_lines(text, _segs("一段", "一行。")) == text


def test_invariant_and_idempotence_on_random_input():
    rng = random.Random(20261011)
    alphabet = _ALPHABET
    for _ in range(300):
        text = "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 1500)))
        text = text.replace("\r", "\r\n").replace("\r\n\n", "\r\n")  # only well-formed CRLF
        out = tr.wrap_lines(text)
        assert tr.strip_breaks(out) == tr.strip_breaks(text)
        assert "\r\r" not in out
        assert all(len(l.rstrip("\r")) <= tr.LINE_MAX for l in out.split("\n"))
        assert tr.wrap_lines(out) == out


def test_long_english_breaks_at_spaces():
    text = "word " * 120  # 600 characters, no segments, no punctuation
    lines = tr.wrap_lines(text).split("\n")
    assert len(lines) > 1 and all(l.endswith(" ") for l in lines[:-1])
    assert all(w == "word" for l in lines for w in l.split())  # never inside a word


def test_long_line_falls_back_to_comma_after_200():
    text = "甲" * 250 + "，" + "乙" * 300
    assert tr.wrap_lines(text).split("\n")[0] == "甲" * 250 + "，"


def test_locating_window_widens_by_the_skipped_length():
    segs = _segs("第一段。", "寫法甲" * 34, "第三段。", "第四段。")  # second segment was rewritten (102 chars)
    text = "第一段。" + "別種寫法" * 25 + "第三段。第四段。"
    assert tr.wrap_lines(text, segs) == "第一段。\n" + "別種寫法" * 25 + "第三段。\n第四段。"


def test_convert_is_needed_to_find_a_converted_segment():
    segs = _segs("这是简体。", "这是繁体。", "第三。")
    text = "这是简体。這是繁體。第三。"
    conv = lambda s: s.replace("这是繁体", "這是繁體")
    assert tr.wrap_lines(text, segs, convert=conv) == "这是简体。\n這是繁體。\n第三。"
    assert tr.wrap_lines(text, segs) != "这是简体。\n這是繁體。\n第三。"  # without convert it is not found


def test_segment_end_at_crlf_adds_no_empty_line():
    text = "甲。\r\n乙。"
    assert tr.wrap_lines(text, _segs("甲。", "乙。")) == text


def test_faster_whisper_space_stays_at_the_end_of_the_line():
    segs = _segs("hello there.", "bye")
    assert tr.wrap_lines("hello there. bye", segs) == "hello there. \nbye"


def test_tail_of():
    assert tr.tail_of("第一行\n最後一行的開頭十二個字之後還有\n\n") == "行的開頭十二個字之後還有"
    # short last lines and trailing spaces, as in real caches: the tail runs across line breaks
    assert tr.tail_of("前面的一句話\n再來一句話結束了\n拜拜 \n!\n") == "話再來一句話結束了拜拜!"
    assert tr.tail_of("abc def\nghi") == "abcdefghi" and tr.tail_of("a b", 12) == "ab"
    # one long line: the tail is the end of the file, not its start
    assert tr.tail_of("開頭" + "字" * 50 + "結尾十二個字的尾巴在這裡呀") == "結尾十二個字的尾巴在這裡呀"[-12:]
    assert tr.tail_of("") == "" and tr.tail_of("\n \n") == ""


def test_closer_absorption_never_pushes_a_line_past_line_max():
    text = "甲" * 398 + "。" + "」" * 5 + "乙" * 300  # sentence end at offset 399, five closers after it
    out = tr.wrap_lines(text)
    lines = out.split("\n")
    assert all(len(l) <= tr.LINE_MAX for l in lines)
    assert tr.strip_breaks(out) == text
    assert tr.wrap_lines(out) == out


def test_segmented_invariant_and_idempotence_on_random_input():
    rng = random.Random(20261011)
    cut_rng = random.Random(7)
    for _ in range(300):
        text = "".join(rng.choice(_ALPHABET) for _ in range(rng.randint(0, 1500)))
        text = text.replace("\r", "\r\n").replace("\r\n\n", "\r\n")  # only well-formed CRLF
        segs, i = [], 0
        while i < len(text):
            n = cut_rng.randint(1, 80)
            segs.append({"start": 0, "end": 0, "text": text[i:i + n]})
            i += n
        out = tr.wrap_lines(text, segs)
        assert tr.strip_breaks(out) == tr.strip_breaks(text)
        assert "\r\r" not in out
        assert all(len(l.rstrip("\r")) <= tr.LINE_MAX for l in out.split("\n"))
        assert tr.wrap_lines(out, segs) == out
