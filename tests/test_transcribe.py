import importlib.util
import json
from pathlib import Path

SCRIPT = Path(__file__).parent.parent / "skills" / "audio-tldr" / "scripts" / "transcribe.py"
spec = importlib.util.spec_from_file_location("transcribe", SCRIPT)
transcribe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(transcribe)


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
    path, title = transcribe.download_audio("https://youtu.be/abc", tmp_path)
    assert title == "My Title" and path.endswith(".mp3")
    assert any("-x" in c for c in calls)


def test_zh_conversion_applied_only_for_zh(monkeypatch):
    class FakeConv:
        def convert(self, t):
            return t.replace("简", "簡")  # 简 -> 簡

    monkeypatch.setattr(transcribe, "_get_zh_converter", lambda: FakeConv())
    assert transcribe._maybe_to_traditional("简体", "zh") == "簡体"
    assert transcribe._maybe_to_traditional("简体", "en") == "简体"
    assert transcribe._maybe_to_traditional("", "zh") == ""


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


def _fake_transcription(monkeypatch, tmp_path):
    """Stub download + backend so main() runs the URL path without network/whisper."""
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    monkeypatch.setattr(transcribe, "detect_backend", lambda: "mlx-whisper")

    def fake_download(url, workdir):
        p = workdir / "t.mp3"
        p.write_bytes(b"audio-bytes")
        return str(p), "Fake Title"

    monkeypatch.setattr(transcribe, "download_audio", fake_download)
    monkeypatch.setattr(transcribe, "_run_backend", lambda b, a, l: ("hello", 12.3, "en"))


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
    media, title = transcribe.resolve_apple_podcast(
        "https://podcasts.apple.com/tw/podcast/ep/id150?i=1000776880208")
    assert media == "https://rss.soundon.fm/x.mp3" and title == "EP679"
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
        return str(p), "uuid-title"
    monkeypatch.setattr(transcribe, "download_audio", failing_then_ok)
    monkeypatch.setattr(transcribe, "resolve_apple_podcast",
                        lambda u: ("https://cdn.example/ep42.mp3", "EP42 Title"))
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
