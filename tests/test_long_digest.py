"""v1.0 item 5: long transcripts are read in full on the Ollama path."""
import importlib.util
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fake_ollama import FakeOllama  # noqa: E402

SCRIPT = Path(__file__).resolve().parent.parent / "skills" / "audio-tldr" / "scripts" / "digest.py"
spec = importlib.util.spec_from_file_location("digest_long", SCRIPT)
digest = importlib.util.module_from_spec(spec)
spec.loader.exec_module(digest)


@pytest.fixture(autouse=True)
def _clean(monkeypatch, tmp_path):
    monkeypatch.setenv("AUDIO_TLDR_GLOSSARY", str(tmp_path / "none.txt"))
    monkeypatch.delenv("AUDIO_TLDR_OLLAMA_NUM_CTX", raising=False)
    digest._NUM_CTX_CACHE.clear()


def marked_transcript(lines=4000, width=11):
    """~44k characters, one segment per line, markers near the start, middle and end."""
    body = [f"第{i}段" + "字" * (width - len(str(i)) - 2) for i in range(lines)]
    body[5] += "【標記:開頭的貓】"
    body[lines // 2] += "【標記:中間的船】"
    body[-5] += "【標記:結尾的燈】"
    return "\n".join(body)


MARKERS = ["【標記:開頭的貓】", "【標記:中間的船】", "【標記:結尾的燈】"]


def test_fake_drops_the_beginning_without_truncate_false(monkeypatch):
    """Baseline the probe: the double must reproduce the bug, or the tests below prove nothing."""
    fake = FakeOllama()
    fake.install(monkeypatch, digest)
    reply = digest.call_ollama_chat("http://h", "m", digest.build_messages("rules", marked_transcript()))
    assert MARKERS[0] not in reply and MARKERS[2] in reply


def test_fake_rejects_oversize_with_truncate_false(monkeypatch):
    fake = FakeOllama()
    fake.install(monkeypatch, digest)
    with pytest.raises(digest.OllamaContextExceeded) as e:
        digest.call_ollama_chat("http://h", "m", digest.build_messages("rules", marked_transcript()),
                                truncate=False)
    assert e.value.n_ctx == 8192 and e.value.prompt_tokens > 8192


def test_real_400_body_is_parsed(monkeypatch):
    import io
    import urllib.error
    from fake_ollama import REAL_400

    def real(req, timeout=None):
        raise urllib.error.HTTPError(req.full_url, 400, "Bad Request", {}, io.BytesIO(REAL_400.encode()))
    monkeypatch.setattr(digest.urllib.request, "urlopen", real)
    with pytest.raises(digest.OllamaContextExceeded) as e:
        digest.call_ollama_chat("http://h", "m", [], truncate=False)
    assert (e.value.prompt_tokens, e.value.n_ctx) == (57046, 8192)
    assert "exceeds the available context size" in str(e.value) and "AUDIO_TLDR_OLLAMA_NUM_CTX" in str(e.value)


def test_unparseable_400_is_a_plain_ollama_error(monkeypatch):
    import io
    import urllib.error

    def bad(req, timeout=None):
        raise urllib.error.HTTPError(req.full_url, 400, "Bad Request", {}, io.BytesIO(b"<html>proxy</html>"))
    monkeypatch.setattr(digest.urllib.request, "urlopen", bad)
    with pytest.raises(digest.OllamaError) as e:
        digest.call_ollama_chat("http://h", "m", [], truncate=False)
    assert not isinstance(e.value, digest.OllamaContextExceeded)


def test_silent_truncation_is_detected_from_prompt_eval_count(monkeypatch):
    fake = FakeOllama()
    fake.install(monkeypatch, digest)
    msgs = digest.build_messages("rules", marked_transcript())
    with pytest.raises(digest.OllamaContextExceeded):
        digest.call_ollama_chat("http://h", "m", msgs, options={"num_ctx": 8192},
                                expected_tokens=digest.estimate_tokens(msgs[1]["content"]))


def test_reply_cut_by_num_predict_is_an_error(monkeypatch):
    fake = FakeOllama(done_reason="length")
    fake.install(monkeypatch, digest)
    with pytest.raises(digest.OllamaError, match="cut off"):
        digest.call_ollama_chat("http://h", "m", digest.build_messages("rules", "短"))


def _run_main(tmp_path, monkeypatch, capsys, transcript, *extra):
    t = tmp_path / "transcript.txt"
    t.write_text(transcript, encoding="utf-8")
    i = tmp_path / "i.txt"
    i.write_text("Summarize in Chinese.", encoding="utf-8")
    rc = digest.main([str(t), "--model", "m", "--instructions-file", str(i), *extra])
    cap = capsys.readouterr()
    return rc, cap.out, cap.err


def test_long_transcript_reaches_every_marker(tmp_path, monkeypatch, capsys):
    fake = FakeOllama()
    fake.install(monkeypatch, digest)
    rc, out, err = _run_main(tmp_path, monkeypatch, capsys, marked_transcript())
    assert rc == 0
    assert all(m in out for m in MARKERS), out
    assert "sections" in err
    assert all(r.get("truncate") is False and r["options"]["num_ctx"] == digest.OLLAMA_NUM_CTX_CAP
               and r["options"]["num_predict"] == max(
                   digest.REPLY_RESERVE, digest.OLLAMA_NUM_CTX_CAP
                   - digest.estimate_tokens("".join(m["content"] for m in r["messages"])))
               for r in fake.requests)
    assert len({r["options"]["num_ctx"] for r in fake.requests}) == 1  # never changes -> no reload


def test_short_transcript_is_one_request_with_unchanged_messages(tmp_path, monkeypatch, capsys):
    fake = FakeOllama()
    fake.install(monkeypatch, digest)
    rc, out, err = _run_main(tmp_path, monkeypatch, capsys, "短短的逐字稿。【標記:開頭的貓】")
    assert rc == 0 and len(fake.requests) == 1
    assert fake.requests[0]["messages"] == digest.build_messages("Summarize in Chinese.",
                                                                 "短短的逐字稿。【標記:開頭的貓】", "")


def test_underestimate_falls_back_to_sections(tmp_path, monkeypatch, capsys):
    fake = FakeOllama(tokens_per_char=2.0)  # real tokenizer heavier than the estimate
    fake.install(monkeypatch, digest)
    rc, out, err = _run_main(tmp_path, monkeypatch, capsys, marked_transcript(lines=1800))
    assert rc == 0 and all(m in out for m in MARKERS)
    assert len(fake.requests) >= 4 and "sections" in err  # the single try got 400, then sections + merge


def test_section_that_never_fits_stops_after_three_halvings(tmp_path, monkeypatch, capsys):
    fake = FakeOllama(tokens_per_char=50.0)
    fake.install(monkeypatch, digest)
    rc, out, err = _run_main(tmp_path, monkeypatch, capsys, marked_transcript(lines=400))
    assert rc == 2 and out == "" and "context" in err
    assert len(fake.requests) >= 1 + digest.MAX_HALVINGS  # halving was tried, not an instant give-up


def test_single_line_transcript_that_never_fits_ends(tmp_path, monkeypatch, capsys):
    fake = FakeOllama(tokens_per_char=50.0)
    fake.install(monkeypatch, digest)
    rc, out, err = _run_main(tmp_path, monkeypatch, capsys, "嗯" * 900)  # un-upgraded single line
    assert rc == 2  # terminates (split_lines step never <= 0)


def test_old_ollama_ignoring_truncate_is_caught_and_sectioned(tmp_path, monkeypatch, capsys):
    fake = FakeOllama(honors_truncate=False, tokens_per_char=2.0)
    fake.install(monkeypatch, digest)
    rc, out, err = _run_main(tmp_path, monkeypatch, capsys, marked_transcript(lines=1800))
    assert rc == 0 and all(m in out for m in MARKERS)


def test_truncation_signature_is_caught_even_when_the_estimate_is_below_the_ratio(monkeypatch):
    """Estimate 5000 < 0.625 * 8192, real prompt larger: the server kept n_ctx // 2 (+3) tokens."""
    fake = FakeOllama(count=lambda msgs: 9000, honors_truncate=False)
    fake.install(monkeypatch, digest)
    with pytest.raises(digest.OllamaContextExceeded):
        digest.call_ollama_chat("http://x", "m", [{"role": "user", "content": "x"}],
                                options={"num_ctx": 8192}, expected_tokens=5000)


def test_single_request_may_reply_up_to_the_context_left(monkeypatch):
    fake = FakeOllama()
    fake.install(monkeypatch, digest)
    transcript = "短短的逐字稿。"
    out, sent = digest.run_digest("http://x", "m", "rules", transcript, "")
    assert sent == 1 and len(fake.requests) == 1
    req = fake.requests[0]
    num_ctx = req["options"]["num_ctx"]
    used = digest.estimate_tokens("".join(m["content"] for m in req["messages"]))
    assert req["options"]["num_predict"] == num_ctx - used > digest.REPLY_RESERVE


def test_sectioned_requests_may_reply_up_to_the_context_left_but_never_below_the_reserve(monkeypatch):
    fake = FakeOllama()
    fake.install(monkeypatch, digest)
    out, sent = digest.run_digest("http://x", "m", "rules", marked_transcript(), "")
    assert sent > 2
    for r in fake.requests:
        used = digest.estimate_tokens("".join(m["content"] for m in r["messages"]))
        assert r["options"]["num_predict"] == max(digest.REPLY_RESERVE, r["options"]["num_ctx"] - used)
    assert min(r["options"]["num_predict"] for r in fake.requests) >= digest.REPLY_RESERVE


def test_reply_cut_off_stops_main(tmp_path, monkeypatch, capsys):
    fake = FakeOllama(done_reason="length")
    fake.install(monkeypatch, digest)
    rc, out, err = _run_main(tmp_path, monkeypatch, capsys, "短短的逐字稿。")
    assert rc == 2 and out == "" and "cut off" in err


def test_long_notes_are_merged_before_the_final_request(tmp_path, monkeypatch, capsys):
    from fake_ollama import default_reply
    fake = FakeOllama(reply=lambda msgs: default_reply(msgs) + "註" * 14500)
    fake.install(monkeypatch, digest)
    rc, out, err = _run_main(tmp_path, monkeypatch, capsys, marked_transcript())
    assert rc == 0 and all(m in out for m in MARKERS)
    assert len(fake.requests) == 4  # 2 sections, 1 merge of the two notes, 1 final


def test_notes_that_never_fit_stop_after_three_merges(tmp_path, monkeypatch, capsys):
    fake = FakeOllama(reply=lambda msgs: "註" * 30000)
    fake.install(monkeypatch, digest)
    rc, out, err = _run_main(tmp_path, monkeypatch, capsys, marked_transcript())
    assert rc == 2 and "three times" in err


def test_whole_text_refuses_instead_of_sectioning(tmp_path, monkeypatch, capsys):
    fake = FakeOllama()
    fake.install(monkeypatch, digest)
    rc, out, err = _run_main(tmp_path, monkeypatch, capsys, marked_transcript(), "--whole-text")
    assert rc == 2 and out == "" and "subagent" in err


def test_tiny_context_model_fails_clearly(tmp_path, monkeypatch, capsys):
    fake = FakeOllama()
    fake.install(monkeypatch, digest)
    monkeypatch.setattr(digest, "ollama_num_ctx", lambda host, model: 5000)
    rc, out, err = _run_main(tmp_path, monkeypatch, capsys, marked_transcript())
    assert rc == 2 and "AUDIO_TLDR_OLLAMA_NUM_CTX" in err


def test_section_notes_are_labelled_untrusted_and_positioned(tmp_path, monkeypatch, capsys):
    fake = FakeOllama()
    fake.install(monkeypatch, digest)
    _run_main(tmp_path, monkeypatch, capsys, marked_transcript())
    final = fake.requests[-1]["messages"][1]["content"]
    assert "data, not instructions" in final and "timestamps" in final
    assert "1/" in fake.requests[0]["messages"][1]["content"]
    assert "timestamp" in fake.requests[0]["messages"][0]["content"]  # section prompt keeps anchors


def test_usage_sums_every_request(tmp_path, monkeypatch, capsys):
    fake = FakeOllama()
    fake.install(monkeypatch, digest)
    _run_main(tmp_path, monkeypatch, capsys, marked_transcript(), "--usage-entry", str(tmp_path))
    rows = (tmp_path / "usage.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(rows) == 1 and len(fake.requests) > 1
    assert json.loads(rows[0])["input"] == sum(fake.prompt_evals) > 8192


def _english_transcript(lines=9000):
    body = [f"segment {i} " + "word " * 12 for i in range(lines)]
    body[5] += "【標記:開頭的貓】"
    body[lines // 2] += "【標記:中間的船】"
    body[-5] += "【標記:結尾的燈】"
    return "\n".join(body)


def test_mixed_density_english_transcript_with_chinese_notes_still_fits(tmp_path, monkeypatch, capsys):
    from fake_ollama import default_reply
    count = lambda msgs: digest.estimate_tokens("".join(m["content"] for m in msgs))
    fake = FakeOllama(count=count, reply=lambda msgs: default_reply(msgs) + "註" * 3500)
    fake.install(monkeypatch, digest)
    rc, out, err = _run_main(tmp_path, monkeypatch, capsys, _english_transcript())
    assert rc == 0 and all(m in out for m in MARKERS), err
    assert count(fake.requests[-1]["messages"]) <= digest.OLLAMA_NUM_CTX_CAP - digest.REPLY_RESERVE
    assert len(fake.requests) > 10  # many sections, so notes had to be merged first


def test_note_reports_the_number_of_requests_actually_sent(tmp_path, monkeypatch, capsys):
    fake = FakeOllama()
    fake.install(monkeypatch, digest)
    rc, out, err = _run_main(tmp_path, monkeypatch, capsys, marked_transcript())
    assert rc == 0 and f"({len(fake.requests)} requests)" in err


def test_short_text_with_whole_text_is_one_request(tmp_path, monkeypatch, capsys):
    fake = FakeOllama()
    fake.install(monkeypatch, digest)
    rc, out, err = _run_main(tmp_path, monkeypatch, capsys, "短短的逐字稿。", "--whole-text")
    assert rc == 0 and len(fake.requests) == 1


def test_unmergeable_notes_stop_without_resending_the_same_requests(tmp_path, monkeypatch, capsys):
    fake = FakeOllama(reply=lambda msgs: "註" * 30000)
    fake.install(monkeypatch, digest)
    rc, out, err = _run_main(tmp_path, monkeypatch, capsys, marked_transcript())
    assert rc == 2 and "three times" in err
    assert len(fake.requests) <= 2 + 1  # 2 sections + one failed merge attempt, then stop


def test_unknown_timestamps_are_removed_including_hours():
    known = digest.cue_times("[00:05] 開場\n[59:59] 快一小時\n[1:02:03] 超過一小時")
    text, removed = digest.strip_unknown_timestamps(
        "重點一 [00:05]\n重點二 [1:02:03]\n編的 [12:34]\n也是編的 [2:00:00]", known)
    assert removed == 2
    assert "[00:05]" in text and "[1:02:03]" in text and "[12:34]" not in text and "[2:00:00]" not in text


def test_main_applies_the_guard_for_subtitle_input(tmp_path, monkeypatch, capsys):
    fake = FakeOllama(reply=lambda msgs: "重點 [00:01]\n捏造 [9:99:99]\n另一個 [33:33]")
    fake.install(monkeypatch, digest)
    srt = tmp_path / "t.srt"
    srt.write_text("1\n00:00:01,000 --> 00:00:02,000\n你好\n", encoding="utf-8")
    i = tmp_path / "i.txt"
    i.write_text("rules", encoding="utf-8")
    assert digest.main([str(srt), "--model", "m", "--instructions-file", str(i)]) == 0
    cap = capsys.readouterr()
    assert "[00:01]" in cap.out and "[33:33]" not in cap.out and "removed 2" in cap.err


def test_guard_applies_after_sectioned_digest(tmp_path, monkeypatch, capsys):
    fake = FakeOllama(reply=lambda msgs: "重點 [00:01]\n捏造 [9:59:59]")
    fake.install(monkeypatch, digest)
    cues = "".join(f"{i}\n00:{i // 60:02d}:{i % 60:02d},000 --> 00:{i // 60:02d}:{i % 60:02d},500\n"
                   f"第{i}段" + "字" * 20 + "\n\n" for i in range(1, 3000))
    srt = tmp_path / "long.srt"
    srt.write_text(cues, encoding="utf-8")
    i = tmp_path / "i.txt"
    i.write_text("rules", encoding="utf-8")
    assert digest.main([str(srt), "--model", "m", "--instructions-file", str(i)]) == 0
    cap = capsys.readouterr()
    assert len(fake.requests) > 1  # it really went in sections
    assert "[00:01]" in cap.out and "[9:59:59]" not in cap.out


def test_plain_text_input_is_not_filtered(tmp_path, monkeypatch, capsys):
    fake = FakeOllama(reply=lambda msgs: "重點 [12:34]")
    fake.install(monkeypatch, digest)
    rc, out, err = _run_main(tmp_path, monkeypatch, capsys, "沒有時間的逐字稿")
    assert "[12:34]" in out


def test_tail_prints_the_last_non_whitespace_characters(tmp_path, capsys):
    p = tmp_path / "t.txt"
    p.write_text("第一行\n最後一行的開頭十二個字之後還有\n", encoding="utf-8")
    assert digest.main(["--tail", str(p)]) == 0
    assert json.loads(capsys.readouterr().out) == {"tail": "行的開頭十二個字之後還有"}
    p.write_text("很長的一行" + "字" * 40 + "結尾在這裡呀 \n拜拜 \n!\n", encoding="utf-8")
    assert digest.main(["--tail", str(p)]) == 0
    assert json.loads(capsys.readouterr().out) == {"tail": "字字字結尾在這裡呀拜拜!"}
    assert digest.main(["--tail", str(tmp_path / "missing.txt")]) == 2


def test_tail_rejects_a_directory_and_an_unreadable_file(tmp_path, monkeypatch, capsys):
    assert digest.main(["--tail", str(tmp_path)]) == 2
    f = tmp_path / "t.txt"
    f.write_text("x\n", encoding="utf-8")

    def boom(_path):
        raise UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid start byte")

    monkeypatch.setattr(digest._transcribe, "_read_text", boom)
    capsys.readouterr()
    assert digest.main(["--tail", str(f)]) == 2
    assert "cannot read" in capsys.readouterr().err


def _padded_reply(msgs):
    from fake_ollama import default_reply
    return default_reply(msgs) + "註" * 200


def test_thinking_tokens_do_not_cut_sectioned_digests_off(tmp_path, monkeypatch, capsys):
    """gemma4 on Ollama thinks by default and the thinking counts against num_predict (real run: 3689 of 4096)."""
    fake = FakeOllama(thinking_tokens=4000, reply=_padded_reply)
    fake.install(monkeypatch, digest)
    rc, out, err = _run_main(tmp_path, monkeypatch, capsys, marked_transcript())
    assert rc == 0, err
    assert all(m in out for m in MARKERS), out


def test_sections_and_merges_ask_not_to_think_final_and_single_use_the_default(tmp_path, monkeypatch, capsys):
    from fake_ollama import default_reply
    fake = FakeOllama(reply=lambda msgs: default_reply(msgs) + "註" * 14500)
    fake.install(monkeypatch, digest)
    rc, out, err = _run_main(tmp_path, monkeypatch, capsys, marked_transcript())
    assert rc == 0 and len(fake.requests) == 4  # 2 sections, 1 merge, 1 final
    assert [r.get("think") for r in fake.requests] == [False, False, False, None]
    assert "think" not in fake.requests[-1]
    single = FakeOllama()
    single.install(monkeypatch, digest)
    digest.run_digest("http://x", "m", "rules", "短短的逐字稿。", "")
    assert len(single.requests) == 1 and "think" not in single.requests[0]


def test_every_request_may_reply_up_to_the_context_left(tmp_path, monkeypatch, capsys):
    from fake_ollama import default_reply
    for reply in (default_reply, lambda msgs: default_reply(msgs) + "註" * 14500):  # sections only / with a merge
        fake = FakeOllama(reply=reply)
        fake.install(monkeypatch, digest)
        digest.run_digest("http://x", "m", "rules", marked_transcript(), "")
        assert len(fake.requests) >= 3
        for r in fake.requests:
            used = digest.estimate_tokens("".join(m["content"] for m in r["messages"]))
            assert r["options"]["num_predict"] == max(digest.REPLY_RESERVE, r["options"]["num_ctx"] - used)


def test_call_ollama_chat_sends_think_only_when_given(monkeypatch):
    fake = FakeOllama()
    fake.install(monkeypatch, digest)
    digest.call_ollama_chat("http://h", "m", digest.build_messages("rules", "短"))
    digest.call_ollama_chat("http://h", "m", digest.build_messages("rules", "短"), think=False)
    assert "think" not in fake.requests[0] and fake.requests[1]["think"] is False
