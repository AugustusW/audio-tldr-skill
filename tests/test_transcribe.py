import importlib.util
import json
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parent.parent / "skills" / "audio-tldr" / "scripts" / "transcribe.py"
spec = importlib.util.spec_from_file_location("transcribe", SCRIPT)
transcribe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(transcribe)


@pytest.fixture(autouse=True)
def fetch_calls(monkeypatch):
    """Cache hits backfill context.json through yt-dlp / the iTunes lookup.
    This machine has yt-dlp and CI does not, so an unstubbed hit would pass
    here for the wrong reason or reach the network. Stub it everywhere; tests
    that exercise the fetch re-patch fetch_context themselves.

    The stub records instead of raising: the backfill swallows every exception
    by design, so a raising stub could never make a test fail."""
    calls = []
    def record(source):
        calls.append(source)
        return {}
    monkeypatch.setattr(transcribe, "fetch_context", record)
    return calls


def test_cache_key_url_strips_tracking_params():
    a = transcribe.cache_key("https://youtu.be/abc123?si=XYZ&utm_source=share")
    b = transcribe.cache_key("https://youtu.be/abc123")
    assert a == b and len(a) == 64


def test_cache_key_url_keeps_meaningful_params():
    a = transcribe.cache_key("https://www.youtube.com/watch?v=abc123")
    b = transcribe.cache_key("https://www.youtube.com/watch?v=def456")
    assert a != b


def test_cache_key_local_file_by_content(tmp_path):
    f1 = tmp_path / "a.mp3"
    f1.write_bytes(b"same-bytes")
    f2 = tmp_path / "b.mp3"
    f2.write_bytes(b"same-bytes")
    assert transcribe.cache_key(str(f1)) == transcribe.cache_key(str(f2))


def test_load_cached_miss_and_corrupt(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    assert transcribe.load_cached("deadbeef") is None  # miss
    d = tmp_path / "audio-tldr" / "deadbeef"
    d.mkdir(parents=True)
    (d / "meta.json").write_text(json.dumps({"transcript_path": str(d / "gone.txt")}))
    assert transcribe.load_cached("deadbeef") is None  # transcript missing -> miss


def test_detect_backend_priority_mlx_first(monkeypatch):
    monkeypatch.setattr(transcribe, "_module_available", lambda m: m == "mlx_whisper")
    monkeypatch.setattr(transcribe.shutil, "which", lambda c: "/usr/bin/" + c)
    assert transcribe.detect_backend() == "mlx-whisper"


def test_detect_backend_whisper_cpp_needs_model_env(monkeypatch, tmp_path):
    monkeypatch.setattr(transcribe, "_module_available", lambda m: False)
    monkeypatch.setattr(
        transcribe.shutil, "which",
        lambda c: "/opt/homebrew/bin/whisper-cli" if c == "whisper-cli" else None)
    monkeypatch.delenv("AUDIO_TLDR_WHISPER_CPP_MODEL", raising=False)
    assert transcribe.detect_backend() is None  # binary without model env -> skip
    model = tmp_path / "ggml-base.bin"
    model.write_bytes(b"x")
    monkeypatch.setenv("AUDIO_TLDR_WHISPER_CPP_MODEL", str(model))
    assert transcribe.detect_backend() == "whisper-cpp"


def test_detect_backend_none(monkeypatch):
    monkeypatch.setattr(transcribe, "_module_available", lambda m: False)
    monkeypatch.setattr(transcribe.shutil, "which", lambda c: None)
    assert transcribe.detect_backend() is None


def test_download_audio_missing_ytdlp(monkeypatch, tmp_path):
    monkeypatch.setattr(transcribe.shutil, "which", lambda c: None)
    try:
        transcribe.download_audio("https://youtu.be/abc", tmp_path)
        assert False, "should raise"
    except transcribe.DownloadError as e:
        assert "yt-dlp" in str(e)


def test_download_audio_invokes_ytdlp(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(transcribe.shutil, "which", lambda c: "/usr/local/bin/yt-dlp")

    def fake_run(cmd, **kw):
        calls.append(cmd)
        (tmp_path / "My Title.mp3").write_bytes(b"audio")

        class R:
            returncode = 0
            stdout = json.dumps({"title": "My Title"})
            stderr = ""
        return R()

    monkeypatch.setattr(transcribe.subprocess, "run", fake_run)
    path, title, info = transcribe.download_audio("https://youtu.be/abc", tmp_path)
    assert title == "My Title" and path.endswith(".mp3")
    assert info == {"title": "My Title"}
    assert any("-x" in c for c in calls)


def test_zh_conversion_applied_only_for_zh(monkeypatch):
    class FakeConv:
        def convert(self, t):
            return t.replace("简", "簡")  # 简 -> 簡

    monkeypatch.setattr(transcribe, "_get_zh_converter", lambda: FakeConv())
    assert transcribe._maybe_to_traditional("简体", "zh") == "簡体"
    assert transcribe._maybe_to_traditional("简体", "en") == "简体"
    assert transcribe._maybe_to_traditional("", "zh") == ""


def test_zh_gate_leaves_traditional_text_untouched(monkeypatch):
    """Already-Traditional text must survive untouched, ambiguous chars included.

    干 / 里 / 吃 are valid Traditional characters that are also the Simplified form
    of 乾 / 裏 / 喫. An unconditional converter pass rewrites them, which is how a
    street address (瑞屏里) turned into a direction word (瑞屏裡) in production.
    """
    pytest.importorskip("opencc")
    import opencc

    monkeypatch.setattr(transcribe, "_get_zh_converter", lambda: opencc.OpenCC("s2twp"))
    for text in (
        "招牌豆干滷到入味",
        "楠梓瑞屏里就有得吃",
        "這份文件很重要，屬於哪一類型",
        "他在群組裡分享了床墊照片",
    ):
        assert transcribe._maybe_to_traditional(text, "zh") == text


def test_zh_gate_still_converts_simplified(monkeypatch):
    """The guard must not cost the feature it guards: Simplified input still converts,
    phrase layer included."""
    pytest.importorskip("opencc")
    import opencc

    monkeypatch.setattr(transcribe, "_get_zh_converter", lambda: opencc.OpenCC("s2twp"))
    assert transcribe._maybe_to_traditional("这家卤味店", "zh") == "這家滷味店"
    assert transcribe._maybe_to_traditional("软件工程师", "zh") == "軟體工程師"


def test_zh_gate_is_per_segment(monkeypatch):
    """Drift is partial: convert the segment that went Simplified, leave the rest."""
    pytest.importorskip("opencc")
    import opencc

    monkeypatch.setattr(transcribe, "_get_zh_converter", lambda: opencc.OpenCC("s2twp"))
    assert (transcribe._maybe_to_traditional("招牌豆干滷到入味。\n这个软件很好用", "zh")
            == "招牌豆干滷到入味。\n這個軟體很好用")


def test_zh_ambiguous_table_is_embedded_not_read_from_package(monkeypatch):
    """The table ships in the source: the official opencc binding has binary .ocd2
    dictionaries, so reading STCharacters.txt is not portable."""
    assert isinstance(transcribe._ZH_AMBIGUOUS, frozenset)
    for ch in "干里吃":
        assert ch in transcribe._ZH_AMBIGUOUS
    for ch in "这卤类软":
        assert ch not in transcribe._ZH_AMBIGUOUS


def test_zh_gate_survives_a_broken_converter(monkeypatch):
    class Boom:
        def convert(self, text):
            raise RuntimeError("boom")

    monkeypatch.setattr(transcribe, "_get_zh_converter", lambda: Boom())
    assert transcribe._maybe_to_traditional("这家店", "zh") == "这家店"


def test_zh_converter_env_off(monkeypatch):
    monkeypatch.setattr(transcribe, "_OPENCC", None)  # reset lazy cache
    monkeypatch.setenv("AUDIO_TLDR_ZH_CONVERT", "off")
    assert transcribe._get_zh_converter() is None


def test_main_cache_hit_skips_everything(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    src = "https://youtu.be/cached1"
    key = transcribe.cache_key(src)
    d = tmp_path / "audio-tldr" / key
    d.mkdir(parents=True)
    t = d / "transcript.txt"
    t.write_text("cached words")
    (d / "meta.json").write_text(json.dumps(
        {"transcript_path": str(t), "title": "T", "duration": 1.0,
         "language": "en", "backend": "mlx-whisper"}))
    rc = transcribe.main([src])
    out = json.loads(capsys.readouterr().out)
    assert rc == 0 and out["cache_hit"] is True and out["transcript_path"] == str(t)


def test_main_no_backend_exit3(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    audio = tmp_path / "x.mp3"
    audio.write_bytes(b"a")
    monkeypatch.setattr(transcribe, "detect_backend", lambda: None)
    rc = transcribe.main([str(audio)])
    assert rc == 3


def _make_entry(base, key, title="t", text="words"):
    d = base / "audio-tldr" / key
    d.mkdir(parents=True)
    t = d / "transcript.txt"
    t.write_text(text)
    (d / "meta.json").write_text(json.dumps(
        {"transcript_path": str(t), "title": title, "source": f"https://x.test/{key}"}))
    return d


def test_cache_info_lists_entries(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    _make_entry(tmp_path, "aaa1")
    _make_entry(tmp_path, "bbb2", title="second")
    rc = transcribe.main(["--cache-info"])
    out = json.loads(capsys.readouterr().out)
    assert rc == 0 and len(out["entries"]) == 2 and out["total_bytes"] > 0
    assert out["retention_days"] is None


def test_clear_single_source(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    src = "https://youtu.be/gone1"
    key = transcribe.cache_key(src)
    d = _make_entry(tmp_path, key)
    keep = _make_entry(tmp_path, "keepme")
    rc = transcribe.main(["--clear", src])
    assert rc == 0 and not d.exists() and keep.exists()


def test_clear_all_requires_yes(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    d = _make_entry(tmp_path, "aaa1")
    assert transcribe.main(["--clear-all"]) == 2
    assert d.exists()
    assert transcribe.main(["--clear-all", "--yes"]) == 0
    assert not d.exists()


def test_retention_prunes_only_when_configured(monkeypatch, tmp_path, capsys):
    import os as _os
    import time as _time
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    old = _make_entry(tmp_path, "old1")
    stale = _time.time() - 40 * 86400
    _os.utime(old / "meta.json", (stale, stale))
    # 未設定 retention → prune 不動
    assert transcribe.prune_expired() == 0 and old.exists()
    # agent 設 30 天 → 40 天前的被清
    assert transcribe.main(["--set-retention", "30"]) == 0
    assert transcribe.prune_expired() == 1 and not old.exists()
    # set-retention off → 移除設定
    assert transcribe.main(["--set-retention", "off"]) == 0
    assert transcribe.load_config().get("retention_days") is None


def test_load_cached_hit(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    d = tmp_path / "audio-tldr" / "cafebabe"
    d.mkdir(parents=True)
    t = d / "transcript.txt"
    t.write_text("hello")
    (d / "meta.json").write_text(json.dumps({"transcript_path": str(t), "title": "x"}))
    got = transcribe.load_cached("cafebabe")
    assert got["title"] == "x"


def _fake_transcription(monkeypatch, tmp_path, segments=None):
    """Stub download + backend so main() runs the URL path without network/whisper.
    `segments` (default None = backend has no segment support) is returned verbatim
    whenever a caller passes want_segments=True, mirroring a real backend."""
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    monkeypatch.setattr(transcribe, "detect_backend", lambda: "mlx-whisper")

    def fake_download(url, workdir):
        p = workdir / "t.mp3"
        p.write_bytes(b"audio-bytes")
        return str(p), "Fake Title", {"title": "Fake Title", "channel": "Fake Channel"}

    monkeypatch.setattr(transcribe, "download_audio", fake_download)
    monkeypatch.setattr(
        transcribe, "_run_backend",
        lambda b, a, l, m=None, want_segments=False: ("hello", 12.3, "en", segments))


def test_keep_audio_moves_mp3_into_cache_entry(monkeypatch, tmp_path, capsys):
    _fake_transcription(monkeypatch, tmp_path)
    rc = transcribe.main(["https://youtu.be/keepme", "--keep-audio"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    key = transcribe.cache_key("https://youtu.be/keepme")
    audio = tmp_path / "audio-tldr" / key / "audio.mp3"
    assert audio.exists() and audio.read_bytes() == b"audio-bytes"
    assert out["audio_path"] == str(audio)


def test_default_deletes_downloaded_audio(monkeypatch, tmp_path, capsys):
    _fake_transcription(monkeypatch, tmp_path)
    rc = transcribe.main(["https://youtu.be/dropme"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    key = transcribe.cache_key("https://youtu.be/dropme")
    assert not (tmp_path / "audio-tldr" / key / "audio.mp3").exists()
    assert "audio_path" not in out


def test_keep_audio_noop_for_local_file(monkeypatch, tmp_path, capsys):
    _fake_transcription(monkeypatch, tmp_path)
    src = tmp_path / "local.mp3"
    src.write_bytes(b"local-bytes")
    rc = transcribe.main([str(src), "--keep-audio"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert "audio_path" not in out          # 本機檔不搬（使用者自己的檔案本來就在）
    assert src.exists()                     # 原檔不動


def test_clear_removes_kept_audio(monkeypatch, tmp_path, capsys):
    _fake_transcription(monkeypatch, tmp_path)
    transcribe.main(["https://youtu.be/clearme", "--keep-audio"])
    capsys.readouterr()
    transcribe.cmd_clear("https://youtu.be/clearme")
    key = transcribe.cache_key("https://youtu.be/clearme")
    assert not (tmp_path / "audio-tldr" / key).exists()


def test_keep_audio_move_failure_preserves_transcript(monkeypatch, tmp_path, capsys):
    _fake_transcription(monkeypatch, tmp_path)
    def failing_move(src, dst):
        raise OSError(28, "No space left on device")
    monkeypatch.setattr(transcribe.shutil, "move", failing_move)
    rc = transcribe.main(["https://youtu.be/nospace", "--keep-audio"])
    captured = capsys.readouterr()
    assert rc == 0                                   # 轉錄成果不因留檔失敗而毀
    out = json.loads(captured.out)
    assert "audio_path" not in out
    assert "could not keep audio" in captured.err
    key = transcribe.cache_key("https://youtu.be/nospace")
    assert (tmp_path / "audio-tldr" / key / "transcript.txt").exists()


def test_force_rerun_preserves_previously_kept_audio(monkeypatch, tmp_path, capsys):
    _fake_transcription(monkeypatch, tmp_path)
    transcribe.main(["https://youtu.be/keepthenforce", "--keep-audio"])
    capsys.readouterr()
    rc = transcribe.main(["https://youtu.be/keepthenforce", "--force"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    key = transcribe.cache_key("https://youtu.be/keepthenforce")
    audio = tmp_path / "audio-tldr" / key / "audio.mp3"
    assert audio.exists()                            # 使用者留存的音檔不被 --force 抹掉
    assert out["audio_path"] == str(audio)           # meta 重新引用，不產孤兒


def test_keep_audio_cache_hit_notes_stderr(monkeypatch, tmp_path, capsys):
    _fake_transcription(monkeypatch, tmp_path)
    transcribe.main(["https://youtu.be/hitnote"])
    capsys.readouterr()
    rc = transcribe.main(["https://youtu.be/hitnote", "--keep-audio"])
    captured = capsys.readouterr()
    assert rc == 0
    assert json.loads(captured.out)["cache_hit"] is True
    assert "cache hit" in captured.err               # 靜默 no-op → 有跡可循


def test_cache_info_size_includes_kept_audio(monkeypatch, tmp_path, capsys):
    _fake_transcription(monkeypatch, tmp_path)
    transcribe.main(["https://youtu.be/sized", "--keep-audio"])
    capsys.readouterr()
    transcribe.cmd_cache_info()
    info = json.loads(capsys.readouterr().out)
    entry = next(e for e in info["entries"] if e["source"] == "https://youtu.be/sized")
    assert entry["size_bytes"] >= len(b"audio-bytes")  # rglob 計入 audio.mp3


# ── Codex validation P0: interpreter auto-selection ──────────────────

def test_reexec_when_backend_in_other_interpreter(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    monkeypatch.delenv("AUDIO_TLDR_REEXECED", raising=False)
    monkeypatch.delenv("AUDIO_TLDR_PYTHON", raising=False)
    monkeypatch.setattr(transcribe, "detect_backend", lambda: None)
    monkeypatch.setattr(transcribe, "_candidate_interpreters", lambda: ["/fake/python312"])
    monkeypatch.setattr(transcribe, "_module_backend_in", lambda p: True)
    calls = []
    def fake_execv(path, argv):
        calls.append((path, argv))
        raise RuntimeError("execv called")   # 真 execv 不返回，用例外模擬
    monkeypatch.setattr(transcribe.os, "execv", fake_execv)
    src = tmp_path / "a.mp3"
    src.write_bytes(b"x")
    try:
        transcribe.main([str(src)])
        assert False, "should have re-exec'd"
    except RuntimeError:
        pass
    assert calls and calls[0][0] == "/fake/python312"
    assert str(src) in calls[0][1]


def test_no_reexec_when_guard_set(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    monkeypatch.setenv("AUDIO_TLDR_REEXECED", "1")
    monkeypatch.delenv("AUDIO_TLDR_PYTHON", raising=False)
    monkeypatch.setattr(transcribe, "detect_backend", lambda: None)
    monkeypatch.setattr(transcribe, "_module_backend_in", lambda p: True)
    src = tmp_path / "a.mp3"
    src.write_bytes(b"x")
    rc = transcribe.main([str(src)])
    assert rc == 3          # loop guard：不再切換，走 install guide


def test_unguarded_main_never_reexecs_under_pytest(monkeypatch, tmp_path, capsys):
    # 不自行設 AUDIO_TLDR_REEXECED 的 main() 測試（如 no-backend exit3 那類）：
    # conftest 的 session-level env 必須擋住 execv，否則在多 Python + MLX 的機器上
    # 整個 pytest process 會被換成真實轉錄（餵假 mp3 → SIGABRT / exit 134）
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    monkeypatch.setattr(transcribe, "detect_backend", lambda: None)
    monkeypatch.setattr(transcribe, "_candidate_interpreters", lambda: ["/fake/py"])
    monkeypatch.setattr(transcribe, "_module_backend_in", lambda p: True)
    calls = []
    monkeypatch.setattr(transcribe.os, "execv", lambda *a: calls.append(a))
    src = tmp_path / "a.mp3"
    src.write_bytes(b"x")
    rc = transcribe.main([str(src)])
    assert rc == 3 and calls == []


def test_explicit_python_env_reexec(monkeypatch, tmp_path):
    monkeypatch.delenv("AUDIO_TLDR_REEXECED", raising=False)
    fake_py = tmp_path / "mypython"
    fake_py.write_text("#!/bin/sh\n")
    monkeypatch.setenv("AUDIO_TLDR_PYTHON", str(fake_py))
    calls = []
    def fake_execv(path, argv):
        calls.append(path)
        raise RuntimeError("execv called")
    monkeypatch.setattr(transcribe.os, "execv", fake_execv)
    try:
        transcribe.main(["--cache-info"])
        assert False, "should have re-exec'd into AUDIO_TLDR_PYTHON"
    except RuntimeError:
        pass
    assert calls == [str(fake_py)]


# ── Codex validation P0: --doctor ────────────────────────────────────

def test_doctor_reports_environment(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    monkeypatch.delenv("AUDIO_TLDR_PYTHON", raising=False)
    monkeypatch.setattr(transcribe, "_module_available", lambda m: False)
    monkeypatch.setattr(transcribe, "_candidate_interpreters", lambda: ["/fake/py"])
    monkeypatch.setattr(transcribe, "_module_backend_in", lambda p: True)
    rc = transcribe.main(["--doctor"])
    assert rc == 0
    info = json.loads(capsys.readouterr().out)
    assert info["python"]["path"] and info["python"]["version"]
    for k in ("mlx_whisper", "faster_whisper", "whisper_cpp", "openai_whisper"):
        assert k in info["backends"]
    assert "yt_dlp" in info["tools"] and "ffmpeg" in info["tools"]
    assert info["other_interpreters"] == [{"path": "/fake/py", "module_backend": True}]
    assert "selected_backend" in info and "metal" in info


# ── Codex validation P0: Apple Podcasts resolver ─────────────────────

def test_apple_ids_parsing():
    coll, ep, country = transcribe._apple_ids(
        "https://podcasts.apple.com/tw/podcast/ep679/id1500839292?i=1000776880208")
    assert coll == "1500839292" and ep == "1000776880208" and country == "tw"
    assert transcribe._apple_ids("https://youtu.be/abc") is None


def test_resolve_apple_show_page_needs_episode():
    try:
        transcribe.resolve_apple_podcast("https://podcasts.apple.com/tw/podcast/id1500839292")
        assert False
    except transcribe.DownloadError as e:
        assert "episode" in str(e)


def test_resolve_apple_lookup_success(monkeypatch):
    seen_urls = []
    def fake_lookup(url):
        seen_urls.append(url)
        return {"results": [
            {"kind": "podcast", "collectionId": 150, "feedUrl": "https://feed.example/rss"},
            {"trackId": 1000776880208, "trackName": "EP679",
             "episodeUrl": "https://rss.soundon.fm/x.mp3",
             "feedUrl": "https://feed.example/rss"}]}
    monkeypatch.setattr(transcribe, "_lookup_json", fake_lookup)
    media, title, ctx = transcribe.resolve_apple_podcast(
        "https://podcasts.apple.com/tw/podcast/ep/id150?i=1000776880208")
    assert media == "https://rss.soundon.fm/x.mp3" and title == "EP679"
    assert ctx == {"title": "EP679"}
    assert "id=150" in seen_urls[0]                # collection lookup（單集 id 直查回 0）
    assert "country=tw" in seen_urls[0]            # storefront 必帶，否則台區節目查不到


def test_resolve_apple_episode_not_found(monkeypatch):
    monkeypatch.setattr(transcribe, "_lookup_json", lambda url: {"results": []})
    try:
        transcribe.resolve_apple_podcast("https://podcasts.apple.com/tw/podcast/ep/id150?i=99")
        assert False
    except transcribe.DownloadError as e:
        assert "not found" in str(e)


def test_apple_fallback_keeps_source_identity(monkeypatch, tmp_path, capsys):
    _fake_transcription(monkeypatch, tmp_path)
    apple_url = "https://podcasts.apple.com/tw/podcast/ep/id150?i=42"
    calls = []
    def failing_then_ok(url, workdir):
        calls.append(url)
        if url == apple_url:
            raise transcribe.DownloadError("yt-dlp probe failed: HTTP Error 500")
        p = workdir / "e.mp3"
        p.write_bytes(b"audio-bytes")
        return str(p), "uuid-title", {"title": "uuid-title"}
    monkeypatch.setattr(transcribe, "download_audio", failing_then_ok)
    monkeypatch.setattr(transcribe, "resolve_apple_podcast",
                        lambda u: ("https://cdn.example/ep42.mp3", "EP42 Title", {}))
    rc = transcribe.main([apple_url])
    captured = capsys.readouterr()
    assert rc == 0
    out = json.loads(captured.out)
    assert out["source"] == apple_url                      # cache 識別不斷鏈
    assert out["title"] == "EP42 Title"                    # 標題用 episode 名非 UUID
    assert out["media_url"] == "https://cdn.example/ep42.mp3"
    assert transcribe.cache_key(apple_url) in out["transcript_path"]
    assert calls == [apple_url, "https://cdn.example/ep42.mp3"]


def test_non_apple_download_error_reraises(monkeypatch, tmp_path, capsys):
    _fake_transcription(monkeypatch, tmp_path)
    def failing(url, workdir):
        raise transcribe.DownloadError("boom")
    monkeypatch.setattr(transcribe, "download_audio", failing)
    rc = transcribe.main(["https://youtu.be/xyz"])
    assert rc == 2
    assert "boom" in capsys.readouterr().err


def test_show_page_resolves_to_latest_episode(monkeypatch, tmp_path, capsys):
    _fake_transcription(monkeypatch, tmp_path)
    show_url = "https://podcasts.apple.com/tw/podcast/gooaye/id150"
    monkeypatch.setattr(transcribe, "_lookup_json", lambda url: {"results": [
        {"kind": "podcast", "collectionId": 150},
        {"kind": "podcast-episode", "trackId": 111, "trackName": "EP1",
         "releaseDate": "2026-07-01T00:00:00Z"},
        {"kind": "podcast-episode", "trackId": 222, "trackName": "EP2",
         "releaseDate": "2026-07-18T00:00:00Z"}]})
    rc = transcribe.main([show_url])
    captured = capsys.readouterr()
    assert rc == 0
    out = json.loads(captured.out)
    assert out["source"] == show_url + "?i=222"      # cache 識別綁最新單集，非節目頁
    assert "latest episode" in captured.err and "EP2" in captured.err
    assert transcribe.cache_key(show_url + "?i=222") in out["transcript_path"]


def test_show_page_lookup_failure_exit2(monkeypatch, tmp_path, capsys):
    _fake_transcription(monkeypatch, tmp_path)
    def boom(url):
        raise OSError("network down")
    monkeypatch.setattr(transcribe, "_lookup_json", boom)
    rc = transcribe.main(["https://podcasts.apple.com/tw/podcast/gooaye/id150"])
    assert rc == 2
    assert "Apple lookup failed" in capsys.readouterr().err


def test_show_page_no_episodes_exit2(monkeypatch, tmp_path, capsys):
    _fake_transcription(monkeypatch, tmp_path)
    monkeypatch.setattr(transcribe, "_lookup_json",
                        lambda url: {"results": [{"kind": "podcast", "collectionId": 150}]})
    rc = transcribe.main(["https://podcasts.apple.com/tw/podcast/gooaye/id150"])
    assert rc == 2
    assert "no episodes" in capsys.readouterr().err


# ── Apple canonical cache identity (v0.3.1) ─────────────────────────

def test_cache_key_apple_slug_invariant():
    # Same episode reached via show-page resolution (show slug) vs a directly
    # copied episode link (episode-title slug) must share one cache entry.
    via_show = transcribe.cache_key(
        "https://podcasts.apple.com/tw/podcast/gooaye/id1500839292?i=1000776880208")
    via_episode = transcribe.cache_key(
        "https://podcasts.apple.com/tw/podcast/ep679-%E8%82%A1%E7%99%8C/id1500839292?i=1000776880208")
    assert via_show == via_episode


def test_cache_key_apple_storefront_invariant():
    tw = transcribe.cache_key(
        "https://podcasts.apple.com/tw/podcast/gooaye/id1500839292?i=1000776880208")
    us = transcribe.cache_key(
        "https://podcasts.apple.com/us/podcast/gooaye/id1500839292?i=1000776880208")
    assert tw == us


def test_cache_key_apple_different_episodes_differ():
    a = transcribe.cache_key(
        "https://podcasts.apple.com/tw/podcast/gooaye/id1500839292?i=1000776880208")
    b = transcribe.cache_key(
        "https://podcasts.apple.com/tw/podcast/gooaye/id1500839292?i=1000776880209")
    assert a != b


def test_cache_key_apple_show_page_without_episode_falls_back():
    # A bare show page (no ?i=) has no episode identity — keep URL-based key.
    a = transcribe.cache_key("https://podcasts.apple.com/tw/podcast/gooaye/id1500839292")
    b = transcribe.cache_key("https://podcasts.apple.com/tw/podcast/other/id1500839292")
    assert a != b


# ── Repetition collapse (v0.3.1) ────────────────────────────────────

def test_collapse_repeated_tail_phrase():
    text = "正常內容講完了。" + "謝謝大家收看。" * 20
    out = transcribe._collapse_repetitions(text)
    assert out == "正常內容講完了。謝謝大家收看。"


def test_collapse_repeated_space_joined_segments():
    text = "Real content here. " + " ".join(["Thanks for watching"] * 10)
    out = transcribe._collapse_repetitions(text)
    assert out == "Real content here. Thanks for watching"


def test_collapse_keeps_double_repeats():
    text = "很好 很好 接下來進正題"
    assert transcribe._collapse_repetitions(text) == text


def test_collapse_leaves_normal_text_untouched(monkeypatch):
    text = "今天聊三件事：第一，市場；第二，財報；第三，展望。"
    assert transcribe._collapse_repetitions(text) == text


def test_collapse_disabled_by_env(monkeypatch):
    monkeypatch.setenv("AUDIO_TLDR_DEREPEAT", "off")
    text = "尾端幻覺。" * 10
    assert transcribe._collapse_repetitions(text) == text


# ── Model selection (--model flag, v0.3.2) ──────────────────────────

def test_resolve_model_default_turbo(monkeypatch):
    monkeypatch.delenv("AUDIO_TLDR_MODEL", raising=False)
    assert transcribe.resolve_model("mlx-whisper", None) == "mlx-community/whisper-large-v3-turbo"
    assert transcribe.resolve_model("faster-whisper", None) == "large-v3-turbo"
    assert transcribe.resolve_model("openai-whisper", None) == "large-v3-turbo"


def test_resolve_model_short_name_maps_per_backend(monkeypatch):
    monkeypatch.delenv("AUDIO_TLDR_MODEL", raising=False)
    assert transcribe.resolve_model("mlx-whisper", "small") == "mlx-community/whisper-small"
    assert transcribe.resolve_model("faster-whisper", "small") == "small"


def test_resolve_model_whisper_prefix_normalized(monkeypatch):
    monkeypatch.delenv("AUDIO_TLDR_MODEL", raising=False)
    assert transcribe.resolve_model("faster-whisper", "whisper-large-v3-turbo") == "large-v3-turbo"
    assert transcribe.resolve_model("mlx-whisper", "whisper-large-v3-turbo") == \
        "mlx-community/whisper-large-v3-turbo"


def test_resolve_model_full_repo_path_passthrough(monkeypatch):
    monkeypatch.delenv("AUDIO_TLDR_MODEL", raising=False)
    assert transcribe.resolve_model("mlx-whisper", "someone/custom-whisper") == "someone/custom-whisper"


def test_resolve_model_cli_beats_env(monkeypatch):
    monkeypatch.setenv("AUDIO_TLDR_MODEL", "medium")
    assert transcribe.resolve_model("faster-whisper", "large-v3") == "large-v3"
    assert transcribe.resolve_model("faster-whisper", None) == "medium"


# ── Model aliases (v0.7.0) ──────────────────────────────────────────

def test_resolve_model_breeze_alias_maps_per_backend(monkeypatch):
    monkeypatch.delenv("AUDIO_TLDR_MODEL", raising=False)
    assert transcribe.resolve_model("mlx-whisper", "breeze-asr-25") == \
        "eoleedi/Breeze-ASR-25-mlx"
    assert transcribe.resolve_model("faster-whisper", "breeze-asr-25") == \
        "SoybeanMilk/faster-whisper-Breeze-ASR-25"


def test_resolve_model_breeze_alias_case_insensitive(monkeypatch):
    monkeypatch.delenv("AUDIO_TLDR_MODEL", raising=False)
    assert transcribe.resolve_model("mlx-whisper", "Breeze-ASR-25") == \
        "eoleedi/Breeze-ASR-25-mlx"


def test_resolve_model_breeze_alias_unsupported_backend_raises(monkeypatch):
    monkeypatch.delenv("AUDIO_TLDR_MODEL", raising=False)
    with pytest.raises(transcribe.ModelAliasError) as e:
        transcribe.resolve_model("openai-whisper", "breeze-asr-25")
    msg = str(e.value)
    assert "openai-whisper" in msg
    assert "mlx-whisper" in msg and "faster-whisper" in msg  # names the backends that DO work


def test_resolve_model_breeze_alias_via_env(monkeypatch):
    monkeypatch.setenv("AUDIO_TLDR_MODEL", "breeze-asr-25")
    assert transcribe.resolve_model("faster-whisper", None) == \
        "SoybeanMilk/faster-whisper-Breeze-ASR-25"


def test_main_unsupported_alias_fails_before_download(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    monkeypatch.delenv("AUDIO_TLDR_MODEL", raising=False)
    monkeypatch.setattr(transcribe, "detect_backend", lambda: "openai-whisper")

    def _no_download(*a, **kw):
        raise AssertionError("download must not run when the alias cannot resolve")
    monkeypatch.setattr(transcribe, "download_audio", _no_download)
    monkeypatch.setattr(transcribe, "_resolve_show_to_latest", lambda s: (s, None))
    rc = transcribe.main(["https://example.com/ep.mp3", "--model", "breeze-asr-25"])
    assert rc == 2
    err = capsys.readouterr().err
    # The alias error itself, not a swallowed AssertionError from the download stub.
    assert "no known openai-whisper conversion" in err
    assert "download must not run" not in err


# ── OpenCC default config (v0.3.3) ──────────────────────────────────

def test_zh_convert_default_is_s2twp(monkeypatch):
    import sys, types
    seen = {}
    fake = types.ModuleType("opencc")
    fake.OpenCC = lambda cfg: seen.setdefault("cfg", cfg) or object()
    monkeypatch.setitem(sys.modules, "opencc", fake)
    monkeypatch.delenv("AUDIO_TLDR_ZH_CONVERT", raising=False)
    monkeypatch.setattr(transcribe, "_OPENCC", None)  # reset lazy cache
    transcribe._get_zh_converter()
    assert seen["cfg"] == "s2twp"


# ── Subtitle export: timestamp formatting (v0.6.0) ──────────────────

def test_timestamp_zero():
    assert transcribe._format_timestamp(0, ",") == "00:00:00,000"
    assert transcribe._format_timestamp(0, ".") == "00:00:00.000"


def test_timestamp_over_one_hour():
    assert transcribe._format_timestamp(3661.5, ",") == "01:01:01,500"
    assert transcribe._format_timestamp(3661.5, ".") == "01:01:01.500"


def test_timestamp_millisecond_rounding_half_up():
    # Decimal-based rounding avoids binary-float .5 landmines (e.g. round()'s
    # banker's rounding); 1.2345s -> 1234.5ms -> rounds up to 1235ms.
    assert transcribe._format_timestamp(1.2345, ",") == "00:00:01,235"


def test_timestamp_rounding_rolls_over_to_next_minute():
    # 59.9995s rounds up to exactly 60.000s -> carries into the minutes field.
    assert transcribe._format_timestamp(59.9995, ",") == "00:01:00,000"


def test_timestamp_negative_clamped_to_zero():
    assert transcribe._format_timestamp(-0.5, ",") == "00:00:00,000"


# ── Subtitle export: SRT/VTT formatting (v0.6.0) ─────────────────────

def test_format_srt_basic():
    segments = [{"start": 0.0, "end": 1.234, "text": "Hello"},
                {"start": 1.234, "end": 3.0, "text": "World"}]
    assert transcribe.format_srt(segments) == (
        "1\n00:00:00,000 --> 00:00:01,234\nHello\n\n"
        "2\n00:00:01,234 --> 00:00:03,000\nWorld\n"
    )


def test_format_vtt_basic():
    segments = [{"start": 0.0, "end": 1.234, "text": "Hello"},
                {"start": 1.234, "end": 3.0, "text": "World"}]
    assert transcribe.format_vtt(segments) == (
        "WEBVTT\n\n00:00:00.000 --> 00:00:01.234\nHello\n\n"
        "00:00:01.234 --> 00:00:03.000\nWorld\n"
    )


def test_format_srt_strips_and_skips_empty_segments():
    segments = [{"start": 0.0, "end": 1.0, "text": "   "},
                {"start": 1.0, "end": 2.0, "text": "  Real line  "}]
    out = transcribe.format_srt(segments)
    assert out == "1\n00:00:01,000 --> 00:00:02,000\nReal line\n"


def test_format_vtt_no_segments_is_bare_header():
    assert transcribe.format_vtt([]) == "WEBVTT\n"


def test_format_srt_no_segments_is_empty():
    assert transcribe.format_srt([]) == ""


# ── Subtitle export: per-backend segment capture (v0.6.0) ────────────

def test_run_backend_mlx_whisper_captures_segments(monkeypatch):
    import sys, types
    fake = types.ModuleType("mlx_whisper")

    def fake_transcribe(path, **kw):
        return {
            "text": "hello world",
            "language": "en",
            "segments": [
                {"start": 0.0, "end": 1.0, "text": " hello"},
                {"start": 1.0, "end": 2.0, "text": " world"},
            ],
        }
    fake.transcribe = fake_transcribe
    monkeypatch.setitem(sys.modules, "mlx_whisper", fake)
    text, dur, lang, segments = transcribe._run_backend(
        "mlx-whisper", "/tmp/x.mp3", None, want_segments=True)
    assert text == "hello world" and lang == "en" and dur == 2.0
    assert segments == [{"start": 0.0, "end": 1.0, "text": "hello"},
                         {"start": 1.0, "end": 2.0, "text": "world"}]


def test_run_backend_mlx_whisper_skips_segments_when_not_wanted(monkeypatch):
    import sys, types
    fake = types.ModuleType("mlx_whisper")
    fake.transcribe = lambda path, **kw: {
        "text": "hi", "language": "en",
        "segments": [{"start": 0.0, "end": 1.0, "text": "hi"}],
    }
    monkeypatch.setitem(sys.modules, "mlx_whisper", fake)
    _, _, _, segments = transcribe._run_backend(
        "mlx-whisper", "/tmp/x.mp3", None, want_segments=False)
    assert segments is None


def test_run_backend_faster_whisper_captures_segments(monkeypatch):
    import sys, types
    from collections import namedtuple
    Segment = namedtuple("Segment", ["start", "end", "text"])
    Info = namedtuple("Info", ["language"])
    fake = types.ModuleType("faster_whisper")

    class FakeModel:
        def __init__(self, model_id):
            pass

        def transcribe(self, audio_path, language=None, initial_prompt=None):
            segs = [Segment(0.0, 1.5, " hi"), Segment(1.5, 3.0, " there")]
            return iter(segs), Info(language="en")
    fake.WhisperModel = FakeModel
    monkeypatch.setitem(sys.modules, "faster_whisper", fake)
    text, dur, lang, segments = transcribe._run_backend(
        "faster-whisper", "/tmp/x.mp3", None, want_segments=True)
    assert text == "hi there" and lang == "en" and dur == 3.0
    assert segments == [{"start": 0.0, "end": 1.5, "text": "hi"},
                         {"start": 1.5, "end": 3.0, "text": "there"}]


def test_parse_whisper_cpp_json_extracts_segments(tmp_path):
    payload = {
        "transcription": [
            {"timestamps": {"from": "00:00:00,000", "to": "00:00:01,000"},
             "offsets": {"from": 0, "to": 1000}, "text": " hello"},
            {"timestamps": {"from": "00:00:01,000", "to": "00:00:02,000"},
             "offsets": {"from": 1000, "to": 2000}, "text": "  "},  # blank -> dropped
        ]
    }
    p = tmp_path / "audio.16k.wav.json"
    p.write_text(json.dumps(payload))
    segments = transcribe._parse_whisper_cpp_json(p)
    assert segments == [{"start": 0.0, "end": 1.0, "text": "hello"}]


def test_parse_whisper_cpp_json_missing_file_returns_none(tmp_path):
    assert transcribe._parse_whisper_cpp_json(tmp_path / "nope.json") is None


def test_run_backend_whisper_cpp_requests_json_only_when_wanted(monkeypatch, tmp_path):
    monkeypatch.setenv("AUDIO_TLDR_WHISPER_CPP_MODEL", str(tmp_path / "ggml.bin"))
    calls = []

    def fake_run(cmd, **kw):
        calls.append(cmd)
        if cmd[0] == "ffmpeg":
            class R:
                returncode = 0
            return R()
        # whisper-cli invocation: locate the -f wav path and write outputs
        wav = Path(cmd[cmd.index("-f") + 1])
        wav_path = Path(str(wav) + ".txt")
        wav_path.write_text("hello world")
        if "--output-json" in cmd:
            payload = {"transcription": [
                {"offsets": {"from": 0, "to": 1000}, "text": "hello world"}]}
            Path(str(wav) + ".json").write_text(json.dumps(payload))

        class R:
            returncode = 0
        return R()

    monkeypatch.setattr(transcribe.subprocess, "run", fake_run)
    # no --format srt/vtt -> should not request json
    text, dur, lang, segments = transcribe._run_backend(
        "whisper-cpp", "/tmp/in.mp3", None, want_segments=False)
    assert text == "hello world" and segments is None
    assert not any("--output-json" in c for c in calls)

    calls.clear()
    text, dur, lang, segments = transcribe._run_backend(
        "whisper-cpp", "/tmp/in.mp3", None, want_segments=True)
    assert segments == [{"start": 0.0, "end": 1.0, "text": "hello world"}]
    assert any("--output-json" in c for c in calls)


def test_parse_openai_whisper_json_extracts_segments(tmp_path):
    payload = {"text": "hello world", "language": "en", "segments": [
        {"start": 0.0, "end": 1.0, "text": " hello"},
        {"start": 1.0, "end": 2.0, "text": " world"},
    ]}
    p = tmp_path / "out.json"
    p.write_text(json.dumps(payload))
    segments = transcribe._parse_openai_whisper_json(p)
    assert segments == [{"start": 0.0, "end": 1.0, "text": "hello"},
                         {"start": 1.0, "end": 2.0, "text": "world"}]


def test_run_backend_openai_whisper_requests_all_only_when_wanted(monkeypatch, tmp_path):
    calls = []

    def fake_run(cmd, **kw):
        calls.append(cmd)
        outdir = Path(cmd[cmd.index("--output_dir") + 1])
        (outdir / "out.txt").write_text("hello world")
        if "all" in cmd:
            payload = {"text": "hello world", "segments": [
                {"start": 0.0, "end": 1.0, "text": "hello world"}]}
            (outdir / "out.json").write_text(json.dumps(payload))

        class R:
            returncode = 0
        return R()

    monkeypatch.setattr(transcribe.subprocess, "run", fake_run)
    text, dur, lang, segments = transcribe._run_backend(
        "openai-whisper", "/tmp/in.mp3", None, want_segments=False)
    assert text == "hello world" and segments is None
    assert "txt" in calls[0] and "all" not in calls[0]

    calls.clear()
    text, dur, lang, segments = transcribe._run_backend(
        "openai-whisper", "/tmp/in.mp3", None, want_segments=True)
    assert segments == [{"start": 0.0, "end": 1.0, "text": "hello world"}]
    assert "all" in calls[0]


# ── Subtitle export: main() integration (v0.6.0) ─────────────────────

def test_default_format_is_txt_and_writes_no_subtitle_artifacts(monkeypatch, tmp_path, capsys):
    _fake_transcription(monkeypatch, tmp_path,
                         segments=[{"start": 0.0, "end": 1.0, "text": "hi"}])
    rc = transcribe.main(["https://youtu.be/defaultfmt"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    key = transcribe.cache_key("https://youtu.be/defaultfmt")
    d = tmp_path / "audio-tldr" / key
    assert not (d / "segments.json").exists()
    assert not (d / "transcript.srt").exists()
    assert "srt_path" not in out and "segments_path" not in out


def test_format_srt_writes_subtitle_and_segments_cache(monkeypatch, tmp_path, capsys):
    _fake_transcription(monkeypatch, tmp_path,
                         segments=[{"start": 0.0, "end": 1.0, "text": "hi"},
                                   {"start": 1.0, "end": 2.5, "text": "there"}])
    rc = transcribe.main(["https://youtu.be/srtreq", "--format", "srt"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    key = transcribe.cache_key("https://youtu.be/srtreq")
    d = tmp_path / "audio-tldr" / key
    assert (d / "segments.json").exists()
    srt_path = Path(out["srt_path"])
    assert srt_path.exists() and srt_path.read_text().startswith("1\n00:00:00,000")
    assert "there" in srt_path.read_text()


def test_format_vtt_writes_subtitle(monkeypatch, tmp_path, capsys):
    _fake_transcription(monkeypatch, tmp_path,
                         segments=[{"start": 0.0, "end": 1.0, "text": "hi"}])
    rc = transcribe.main(["https://youtu.be/vttreq", "--format", "vtt"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    vtt_path = Path(out["vtt_path"])
    assert vtt_path.read_text().startswith("WEBVTT\n\n00:00:00.000")


def test_format_srt_backend_without_segments_errors_but_keeps_txt_cached(
        monkeypatch, tmp_path, capsys):
    _fake_transcription(monkeypatch, tmp_path, segments=None)  # backend can't provide them
    rc = transcribe.main(["https://youtu.be/nosegs", "--format", "srt"])
    captured = capsys.readouterr()
    assert rc == 2
    assert "does not" in captured.err or "did not" in captured.err
    key = transcribe.cache_key("https://youtu.be/nosegs")
    d = tmp_path / "audio-tldr" / key
    assert (d / "transcript.txt").exists()          # transcription itself is not wasted
    assert not (d / "transcript.srt").exists()


def test_srt_request_on_legacy_cache_errors_with_force_hint(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    src = "https://youtu.be/legacycache"
    key = transcribe.cache_key(src)
    _make_entry(tmp_path, key)  # pre-v0.6.0 shape: no segments_path in meta
    rc = transcribe.main([src, "--format", "srt"])
    captured = capsys.readouterr()
    assert rc == 2
    assert "--force" in captured.err


def test_cache_hit_reformats_from_cached_segments_without_retranscribing(
        monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    src = "https://youtu.be/reformat"
    key = transcribe.cache_key(src)
    d = tmp_path / "audio-tldr" / key
    d.mkdir(parents=True)
    t = d / "transcript.txt"
    t.write_text("hello world")
    seg_path = d / "segments.json"
    seg_path.write_text(json.dumps([{"start": 0.0, "end": 1.5, "text": "hello world"}]))
    (d / "meta.json").write_text(json.dumps({
        "transcript_path": str(t), "title": "t", "language": "en",
        "segments_path": str(seg_path),
    }))

    def boom(*a, **kw):
        raise AssertionError("must not re-transcribe when segments are already cached")
    monkeypatch.setattr(transcribe, "download_audio", boom)
    monkeypatch.setattr(transcribe, "_run_backend", boom)

    rc = transcribe.main([src, "--format", "vtt"])
    out = json.loads(capsys.readouterr().out)
    assert rc == 0 and out["cache_hit"] is True
    vtt_path = Path(out["vtt_path"])
    assert vtt_path.exists() and vtt_path.read_text().startswith("WEBVTT")


def test_cache_hit_reuses_existing_subtitle_file_without_rewriting(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    src = "https://youtu.be/reuse"
    key = transcribe.cache_key(src)
    d = tmp_path / "audio-tldr" / key
    d.mkdir(parents=True)
    t = d / "transcript.txt"
    t.write_text("hello")
    seg_path = d / "segments.json"
    seg_path.write_text(json.dumps([{"start": 0.0, "end": 1.0, "text": "hello"}]))
    srt_path = d / "transcript.srt"
    srt_path.write_text("SENTINEL-ALREADY-WRITTEN")
    (d / "meta.json").write_text(json.dumps({
        "transcript_path": str(t), "title": "t", "language": "en",
        "segments_path": str(seg_path), "srt_path": str(srt_path),
    }))
    rc = transcribe.main([src, "--format", "srt"])
    out = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert srt_path.read_text() == "SENTINEL-ALREADY-WRITTEN"  # not clobbered
    assert out["srt_path"] == str(srt_path)


def test_main_fresh_transcription_records_processing_seconds(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    audio = tmp_path / "talk.mp3"
    audio.write_bytes(b"a")
    monkeypatch.setattr(transcribe, "detect_backend", lambda: "mlx-whisper")
    monkeypatch.setattr(transcribe, "resolve_model", lambda backend, model: "stub-model")
    monkeypatch.setattr(
        transcribe, "_run_backend",
        lambda backend, path, language, model, want_segments=False: ("hello", 3.0, "en", None))
    rc = transcribe.main([str(audio)])
    out = json.loads(capsys.readouterr().out)
    assert rc == 0 and out["cache_hit"] is False
    assert isinstance(out["processing_seconds"], float) and out["processing_seconds"] >= 0
    key = transcribe.cache_key(str(audio))
    meta = json.loads((tmp_path / "audio-tldr" / key / "meta.json").read_text())
    assert meta["processing_seconds"] == out["processing_seconds"]
    t = meta["timings"]
    assert t["backend_call"] == meta["processing_seconds"]
    assert t["download"] is None  # local file: nothing was downloaded
    assert t["postprocess"] >= 0 and t["write"] >= 0


# ── Source context (v0.9.0) ─────────────────────────────────────────

def test_ytdlp_context_extracts_fields():
    info = {"title": " T ", "channel": "真奈特每天都在瞎忙", "uploader": "u",
            "description": "d", "chapters": [{"title": "開場"}, {"title": " "}, {}],
            "tags": ["真奈特", "", None]}
    assert transcribe.ytdlp_context(info) == {
        "title": "T", "channel": "真奈特每天都在瞎忙", "description": "d",
        "chapters": ["開場"], "tags": ["真奈特"]}


def test_ytdlp_context_channel_fallbacks():
    assert transcribe.ytdlp_context({"uploader": "U"})["channel"] == "U"
    assert transcribe.ytdlp_context({"series": "S"})["channel"] == "S"
    assert transcribe.ytdlp_context({"album": "A"})["channel"] == "A"
    assert "channel" not in transcribe.ytdlp_context({"title": "t"})


def test_ytdlp_context_caps():
    info = {"description": "x" * 5000,
            "chapters": [{"title": f"c{i}"} for i in range(60)],
            "tags": [f"t{i}" for i in range(40)]}
    ctx = transcribe.ytdlp_context(info)
    assert len(ctx["description"]) == transcribe.CONTEXT_DESCRIPTION_MAX
    assert len(ctx["chapters"]) == transcribe.CONTEXT_CHAPTERS_MAX
    assert len(ctx["tags"]) == transcribe.CONTEXT_TAGS_MAX


def test_ytdlp_context_tolerates_garbage():
    assert transcribe.ytdlp_context(None) == {}
    assert transcribe.ytdlp_context({"chapters": "nope", "tags": 5, "title": 3}) == {}


def test_apple_context_maps_lookup_fields():
    r0 = {"trackName": "EP1", "collectionName": "Show", "description": "guest: 王小明"}
    assert transcribe.apple_context(r0) == {
        "title": "EP1", "channel": "Show", "description": "guest: 王小明"}


def test_fresh_transcription_writes_context(monkeypatch, tmp_path, capsys):
    _fake_transcription(monkeypatch, tmp_path)
    rc = transcribe.main(["https://youtu.be/ctx1"])
    out = json.loads(capsys.readouterr().out)
    assert rc == 0
    ctx = json.loads(Path(out["context_path"]).read_text())
    assert ctx == {"title": "Fake Title", "channel": "Fake Channel"}
    meta = json.loads((Path(out["transcript_path"]).parent / "meta.json").read_text())
    assert "context_path" not in meta


def test_apple_fallback_context_comes_from_lookup(monkeypatch, tmp_path, capsys):
    _fake_transcription(monkeypatch, tmp_path)
    apple_url = "https://podcasts.apple.com/tw/podcast/ep/id150?i=42"
    def failing_then_ok(url, workdir):
        if url == apple_url:
            raise transcribe.DownloadError("yt-dlp probe failed")
        p = workdir / "e.mp3"
        p.write_bytes(b"a")
        return str(p), "uuid", {"title": "uuid.mp3"}
    monkeypatch.setattr(transcribe, "download_audio", failing_then_ok)
    monkeypatch.setattr(transcribe, "resolve_apple_podcast",
                        lambda u: ("https://cdn.example/e.mp3", "EP42",
                                   {"title": "EP42", "channel": "Show"}))
    transcribe.main([apple_url])
    out = json.loads(capsys.readouterr().out)
    assert json.loads(Path(out["context_path"]).read_text()) == {"title": "EP42", "channel": "Show"}


def test_force_without_new_context_keeps_old_file(monkeypatch, tmp_path, capsys):
    _fake_transcription(monkeypatch, tmp_path)
    src = "https://youtu.be/ctx2"
    transcribe.main([src])
    first = json.loads(capsys.readouterr().out)["context_path"]
    def bare_download(url, workdir):
        p = workdir / "t.mp3"
        p.write_bytes(b"a")
        return str(p), "T", {}
    monkeypatch.setattr(transcribe, "download_audio", bare_download)
    transcribe.main([src, "--force"])
    out = json.loads(capsys.readouterr().out)
    assert out["context_path"] == first
    assert json.loads(Path(first).read_text())["channel"] == "Fake Channel"


def test_local_file_writes_no_context(monkeypatch, tmp_path, capsys):
    _fake_transcription(monkeypatch, tmp_path)
    audio = tmp_path / "x.mp3"
    audio.write_bytes(b"a")
    transcribe.main([str(audio)])
    assert "context_path" not in json.loads(capsys.readouterr().out)


def test_context_path_for_ignores_marker_and_garbage(tmp_path):
    (tmp_path / "context.json").write_text('{"unavailable": true, "checked_date": "x"}')
    assert transcribe.context_path_for(tmp_path) is None
    (tmp_path / "context.json").write_text("not json")
    assert transcribe.context_path_for(tmp_path) is None
    (tmp_path / "context.json").write_text('["list"]')
    assert transcribe.context_path_for(tmp_path) is None


def _cached_url_entry(tmp_path, src):
    d = tmp_path / "audio-tldr" / transcribe.cache_key(src)
    d.mkdir(parents=True)
    t = d / "transcript.txt"
    t.write_text("cached words")
    (d / "meta.json").write_text(json.dumps(
        {"transcript_path": str(t), "title": "T", "duration": 1.0,
         "language": "zh", "backend": "mlx-whisper", "source": src}))
    return d


def test_cache_hit_backfills_context(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    d = _cached_url_entry(tmp_path, "https://youtu.be/old1")
    monkeypatch.setattr(transcribe, "fetch_context", lambda s: {"channel": "真奈特每天都在瞎忙"})
    rc = transcribe.main(["https://youtu.be/old1"])
    out = json.loads(capsys.readouterr().out)
    assert rc == 0 and out["cache_hit"] is True
    assert out["context_path"] == str(d / "context.json")
    assert json.loads((d / "context.json").read_text()) == {"channel": "真奈特每天都在瞎忙"}


def test_cache_hit_backfill_failure_is_silent_and_marked(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    d = _cached_url_entry(tmp_path, "https://youtu.be/old2")
    def boom(s):
        raise subprocess.TimeoutExpired("yt-dlp", 30)
    monkeypatch.setattr(transcribe, "fetch_context", boom)
    rc = transcribe.main(["https://youtu.be/old2"])
    cap = capsys.readouterr()
    out = json.loads(cap.out)
    assert rc == 0 and out["cache_hit"] is True
    assert "context_path" not in out
    assert "note:" in cap.err
    assert json.loads((d / "context.json").read_text())["unavailable"] is True


def test_cache_hit_empty_fetch_is_marked_too(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    d = _cached_url_entry(tmp_path, "https://youtu.be/old2b")
    monkeypatch.setattr(transcribe, "fetch_context", lambda s: {})
    assert transcribe.main(["https://youtu.be/old2b"]) == 0
    assert json.loads((d / "context.json").read_text())["unavailable"] is True


def test_cache_hit_does_not_retry_within_window(monkeypatch, tmp_path, capsys, fetch_calls):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    d = _cached_url_entry(tmp_path, "https://youtu.be/old3")
    recent = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
    (d / "context.json").write_text(json.dumps({"unavailable": True, "checked_date": recent}))
    assert transcribe.main(["https://youtu.be/old3"]) == 0
    assert "context_path" not in json.loads(capsys.readouterr().out)
    assert fetch_calls == []


def test_cache_hit_retries_after_window(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    d = _cached_url_entry(tmp_path, "https://youtu.be/old4")
    old = (datetime.now(timezone.utc) - timedelta(days=8)).isoformat()
    (d / "context.json").write_text(json.dumps({"unavailable": True, "checked_date": old}))
    monkeypatch.setattr(transcribe, "fetch_context", lambda s: {"title": "T"})
    transcribe.main(["https://youtu.be/old4"])
    assert json.loads(capsys.readouterr().out)["context_path"] == str(d / "context.json")


def test_cache_hit_corrupt_context_is_refetched(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    d = _cached_url_entry(tmp_path, "https://youtu.be/old5")
    (d / "context.json").write_text("{broken")
    monkeypatch.setattr(transcribe, "fetch_context", lambda s: {"title": "T"})
    assert transcribe.main(["https://youtu.be/old5"]) == 0
    assert json.loads((d / "context.json").read_text()) == {"title": "T"}


def test_cache_hit_with_context_does_not_fetch(monkeypatch, tmp_path, capsys, fetch_calls):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    d = _cached_url_entry(tmp_path, "https://youtu.be/old6")
    (d / "context.json").write_text(json.dumps({"title": "T"}))
    assert transcribe.main(["https://youtu.be/old6"]) == 0
    assert json.loads(capsys.readouterr().out)["context_path"] == str(d / "context.json")
    assert fetch_calls == []


def test_cache_hit_local_file_never_fetches(monkeypatch, tmp_path, capsys, fetch_calls):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    audio = tmp_path / "x.mp3"
    audio.write_bytes(b"local-audio")
    d = tmp_path / "audio-tldr" / transcribe.cache_key(str(audio))
    d.mkdir(parents=True)
    t = d / "transcript.txt"
    t.write_text("words")
    (d / "meta.json").write_text(json.dumps({"transcript_path": str(t), "title": "x"}))
    assert transcribe.main([str(audio)]) == 0
    assert not (d / "context.json").exists()
    assert fetch_calls == []


def test_fetch_context_apple_uses_lookup_first(monkeypatch):
    monkeypatch.undo()  # drop the autouse stub: this test is about the real fetch
    monkeypatch.setattr(transcribe, "_apple_episode",
                        lambda u: {"trackName": "t", "collectionName": "Show"})
    def no_ytdlp(*a, **k):
        raise AssertionError("yt-dlp must not run when the lookup answered")
    monkeypatch.setattr(transcribe.subprocess, "run", no_ytdlp)
    ctx = transcribe.fetch_context("https://podcasts.apple.com/tw/podcast/x/id1?i=2")
    assert ctx == {"title": "t", "channel": "Show"}


def test_fetch_context_ytdlp_probe_uses_short_timeout(monkeypatch):
    monkeypatch.undo()
    seen = {}
    monkeypatch.setattr(transcribe.shutil, "which", lambda c: "/bin/yt-dlp")
    def fake_run(cmd, **kw):
        seen.update(kw, cmd=cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps({"channel": "C"}), stderr="")
    monkeypatch.setattr(transcribe.subprocess, "run", fake_run)
    assert transcribe.fetch_context("https://youtu.be/z") == {"channel": "C"}
    assert seen["timeout"] == transcribe.CONTEXT_FETCH_TIMEOUT
    assert "--no-download" in seen["cmd"]


def test_fetch_context_without_ytdlp_is_empty(monkeypatch):
    monkeypatch.undo()
    monkeypatch.setattr(transcribe.shutil, "which", lambda c: None)
    assert transcribe.fetch_context("https://youtu.be/z") == {}


# ── Review fixes (pre-PR) ───────────────────────────────────────────

def test_context_write_failure_keeps_the_transcription(monkeypatch, tmp_path, capsys):
    _fake_transcription(monkeypatch, tmp_path)
    def broken(d, ctx):
        raise OSError("disk full")
    monkeypatch.setattr(transcribe, "write_context", broken)
    rc = transcribe.main(["https://youtu.be/ctx-fail"])
    cap = capsys.readouterr()
    assert rc == 0
    out = json.loads(cap.out)
    assert (Path(out["transcript_path"]).parent / "meta.json").exists()
    assert "warning" in cap.err


def test_cache_hit_future_checked_date_is_treated_as_expired(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    d = _cached_url_entry(tmp_path, "https://youtu.be/future")
    future = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()
    (d / "context.json").write_text(json.dumps({"unavailable": True, "checked_date": future}))
    monkeypatch.setattr(transcribe, "fetch_context", lambda s: {"title": "T"})
    transcribe.main(["https://youtu.be/future"])
    assert json.loads(capsys.readouterr().out)["context_path"]


def test_backfill_note_does_not_promise_a_wait_it_could_not_record(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    _cached_url_entry(tmp_path, "https://youtu.be/rofs")
    monkeypatch.setattr(transcribe, "fetch_context", lambda s: {})
    real_write = Path.write_text
    def deny(self, *a, **k):
        if self.name == "context.json":
            raise PermissionError("read-only")
        return real_write(self, *a, **k)
    monkeypatch.setattr(Path, "write_text", deny)
    assert transcribe.main(["https://youtu.be/rofs"]) == 0
    assert "7 days" not in capsys.readouterr().err


def test_fetch_context_apple_does_not_resolve_media(monkeypatch):
    """Backfill needs the lookup's metadata, not a playable URL: a
    subscriber-only episode (no media) still has a show name and notes."""
    monkeypatch.undo()
    calls = []
    def fake_lookup(url):
        calls.append(url)
        return {"results": [{"trackId": 2, "trackName": "EP", "collectionName": "Show"}]}
    monkeypatch.setattr(transcribe, "_lookup_json", fake_lookup)
    monkeypatch.setattr(transcribe, "_enclosure_from_feed",
                        lambda *a: (_ for _ in ()).throw(AssertionError("no feed fetch")))
    ctx = transcribe.fetch_context("https://podcasts.apple.com/tw/podcast/x/id1?i=2")
    assert ctx == {"title": "EP", "channel": "Show"} and len(calls) == 1


def test_fetch_context_apple_unexpected_error_still_tries_ytdlp(monkeypatch):
    monkeypatch.undo()
    monkeypatch.setattr(transcribe, "_lookup_json", lambda url: {"results": "garbage"})
    monkeypatch.setattr(transcribe.shutil, "which", lambda c: "/bin/yt-dlp")
    monkeypatch.setattr(transcribe.subprocess, "run", lambda cmd, **kw: subprocess.CompletedProcess(
        cmd, 0, stdout=json.dumps({"channel": "C"}), stderr=""))
    assert transcribe.fetch_context("https://podcasts.apple.com/tw/podcast/x/id1?i=2") == {"channel": "C"}


# ── Launching yt-dlp (Windows Smart App Control, v0.9.1) ────────────

def test_ytdlp_command_windows_prefers_the_python_module(monkeypatch):
    """A signed python.exe running -m yt_dlp is allowed where the unsigned
    yt-dlp.exe is blocked."""
    monkeypatch.setattr(transcribe, "_module_available", lambda m: m == "yt_dlp")
    monkeypatch.setattr(transcribe.shutil, "which", lambda c: r"C:\bin\yt-dlp.exe")
    assert transcribe.ytdlp_command(windows=True) == [transcribe.sys.executable, "-m", "yt_dlp"]


def test_ytdlp_command_elsewhere_prefers_the_executable(monkeypatch):
    """A Homebrew yt-dlp is usually newer than a stray pip copy; keep using it."""
    monkeypatch.setattr(transcribe, "_module_available", lambda m: m == "yt_dlp")
    monkeypatch.setattr(transcribe.shutil, "which", lambda c: "/opt/homebrew/bin/yt-dlp")
    assert transcribe.ytdlp_command(windows=False) == ["/opt/homebrew/bin/yt-dlp"]


def test_ytdlp_command_falls_back_to_the_module(monkeypatch):
    monkeypatch.setattr(transcribe, "_module_available", lambda m: m == "yt_dlp")
    monkeypatch.setattr(transcribe.shutil, "which", lambda c: None)
    assert transcribe.ytdlp_command(windows=False) == [transcribe.sys.executable, "-m", "yt_dlp"]


@pytest.mark.parametrize("shim", [r"C:\bin\yt-dlp.cmd", r"C:\bin\yt-dlp.BAT"])
def test_ytdlp_command_never_runs_a_batch_file(monkeypatch, shim):
    """A .cmd/.bat runs through cmd.exe, where an & in a URL (…&t=30) splits
    the command line: a crafted link could run a second command."""
    monkeypatch.setattr(transcribe, "_module_available", lambda m: False)
    monkeypatch.setattr(transcribe.shutil, "which", lambda c: shim)
    assert transcribe.ytdlp_command(windows=True) is None


def test_ytdlp_command_resolves_the_full_path(monkeypatch):
    """The bare name would make CreateProcess look for yt-dlp.exe on its own."""
    monkeypatch.setattr(transcribe, "_module_available", lambda m: False)
    monkeypatch.setattr(transcribe.shutil, "which", lambda c: r"C:\Users\u\.local\bin\yt-dlp.exe")
    assert transcribe.ytdlp_command(windows=True) == [r"C:\Users\u\.local\bin\yt-dlp.exe"]


def test_download_audio_runs_the_resolved_launcher(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(transcribe, "ytdlp_command", lambda: ["py", "-m", "yt_dlp"])
    def fake_run(cmd, **kw):
        calls.append(cmd)
        (tmp_path / "T.mp3").write_bytes(b"a")
        return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps({"title": "T"}), stderr="")
    monkeypatch.setattr(transcribe.subprocess, "run", fake_run)
    transcribe.download_audio("https://youtu.be/a?x=1&t=30", tmp_path)
    assert all(c[:3] == ["py", "-m", "yt_dlp"] for c in calls) and len(calls) == 2


def test_download_audio_without_ytdlp_names_the_windows_fix(monkeypatch, tmp_path):
    monkeypatch.setattr(transcribe, "ytdlp_command", lambda: None)
    with pytest.raises(transcribe.DownloadError) as e:
        transcribe.download_audio("https://youtu.be/a", tmp_path)
    assert "pip install yt-dlp" in str(e.value)


def test_fetch_context_uses_the_resolved_launcher(monkeypatch):
    monkeypatch.undo()
    monkeypatch.setattr(transcribe, "ytdlp_command", lambda: ["py", "-m", "yt_dlp"])
    seen = []
    def fake_run(cmd, **kw):
        seen.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps({"channel": "C"}), stderr="")
    monkeypatch.setattr(transcribe.subprocess, "run", fake_run)
    assert transcribe.fetch_context("https://youtu.be/z") == {"channel": "C"}
    assert seen[0][:3] == ["py", "-m", "yt_dlp"]


def test_doctor_shows_how_ytdlp_will_be_launched(monkeypatch, tmp_path, capsys):
    """On Windows the question is usually "which yt-dlp is it trying to run?"."""
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    monkeypatch.setattr(transcribe, "_candidate_interpreters", lambda: [])
    monkeypatch.setattr(transcribe, "ytdlp_command", lambda: ["C:\\py.exe", "-m", "yt_dlp"])
    transcribe.main(["--doctor"])
    info = json.loads(capsys.readouterr().out)
    assert info["tools"]["yt_dlp"] is True
    assert info["tools"]["yt_dlp_launcher"] == ["C:\\py.exe", "-m", "yt_dlp"]


def test_doctor_launcher_is_null_without_ytdlp(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    monkeypatch.setattr(transcribe, "_candidate_interpreters", lambda: [])
    monkeypatch.setattr(transcribe, "ytdlp_command", lambda: None)
    transcribe.main(["--doctor"])
    info = json.loads(capsys.readouterr().out)
    assert info["tools"]["yt_dlp"] is False and info["tools"]["yt_dlp_launcher"] is None
