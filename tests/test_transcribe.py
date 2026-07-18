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
