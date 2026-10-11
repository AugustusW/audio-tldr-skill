"""Cache schema v1: resolution, atomic writes, upgrades, compatibility.

Kept in its own file so CI's Windows job can run exactly these tests:
os.replace and os.utime behave differently there."""
import importlib.util
import json
import locale
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parent.parent / "skills" / "audio-tldr" / "scripts" / "transcribe.py"
spec = importlib.util.spec_from_file_location("transcribe_cache", SCRIPT)
transcribe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(transcribe)


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """URL cache hits backfill context.json; never let a test reach the network."""
    monkeypatch.setattr(transcribe, "fetch_context", lambda source: {})


def test_resolve_entry_file_uses_only_the_entry_folder(tmp_path):
    d = tmp_path / "entry"
    d.mkdir()
    (d / "transcript.txt").write_text("x")
    assert transcribe.resolve_entry_file(d, "transcript") == d / "transcript.txt"
    assert transcribe.resolve_entry_file(d, "segments") is None


def test_read_json_falls_back_to_the_locale_encoding(tmp_path, monkeypatch):
    """v0.9.1 on Windows wrote meta.json in the locale encoding (cp950 on a
    Traditional Chinese system), not UTF-8."""
    p = tmp_path / "meta.json"
    p.write_bytes(json.dumps({"title": "股癌"}, ensure_ascii=False).encode("cp950"))
    _stub_locale(monkeypatch, "cp950")
    assert transcribe._read_json(p) == {"title": "股癌"}


def test_read_json_missing_or_corrupt_is_none(tmp_path):
    assert transcribe._read_json(tmp_path / "nope.json") is None
    bad = tmp_path / "bad.json"
    bad.write_text("{half")
    assert transcribe._read_json(bad) is None


def test_atomic_write_replaces_and_keeps_mtime(tmp_path):
    p = tmp_path / "meta.json"
    p.write_text("old")
    old_ns = 1_600_000_000_000_000_000
    transcribe._atomic_write_text(p, "new", mtime_ns=old_ns)
    assert p.read_text() == "new"
    assert abs(p.stat().st_mtime_ns - old_ns) <= 2_000_000_000  # exFAT: 2 s
    assert not list(tmp_path.glob(".meta.json.tmp-*"))


def test_atomic_write_failure_leaves_original_and_no_temp(tmp_path, monkeypatch):
    p = tmp_path / "meta.json"
    p.write_text("old")
    def boom(src, dst):
        raise OSError("disk full")
    monkeypatch.setattr(transcribe.os, "replace", boom)
    with pytest.raises(OSError):
        transcribe._atomic_write_text(p, "new")
    assert p.read_text() == "old"
    assert not list(tmp_path.glob(".meta.json.tmp-*"))


def test_atomic_write_retries_permission_error(tmp_path, monkeypatch):
    """Windows raises PermissionError while another process has the target open."""
    p = tmp_path / "meta.json"
    p.write_text("old")
    real_replace = os.replace
    calls = []
    def flaky(src, dst):
        calls.append(1)
        if len(calls) < 3:
            raise PermissionError("in use")
        real_replace(src, dst)
    monkeypatch.setattr(transcribe.os, "replace", flaky)
    monkeypatch.setattr(transcribe.time, "sleep", lambda s: None)
    transcribe._atomic_write_text(p, "new")
    assert p.read_text() == "new" and len(calls) == 3


from datetime import datetime, timezone


def _v0_entry(base, files=("transcript.txt", "segments.json"), old_root="/old/place"):
    d = base / "entry"
    d.mkdir()
    for name in files:
        (d / name).write_text("x")
    meta = {"title": "T", "source": "https://x.test/a", "language": "zh",
            "transcript_path": f"{old_root}/transcript.txt"}
    if "segments.json" in files:
        meta["segments_path"] = f"{old_root}/segments.json"
    (d / "meta.json").write_text(json.dumps(meta))
    return d, meta


def test_entry_cached_ts_prefers_cached_date_then_created_then_mtime(tmp_path):
    d, meta = _v0_entry(tmp_path)
    os.utime(d / "meta.json", (1_500_000_000, 1_500_000_000))
    assert transcribe.entry_cached_ts(d, meta) == 1_500_000_000
    assert transcribe.entry_cached_ts(d, {"created": "2020-01-02T03:04:05"}) == \
        datetime(2020, 1, 2, 3, 4, 5).astimezone().timestamp()
    stamp = "2021-06-01T00:00:00+00:00"
    assert transcribe.entry_cached_ts(d, {"cached_date": stamp, "created": "2020-01-01T00:00:00"}) == \
        datetime(2021, 6, 1, tzinfo=timezone.utc).timestamp()
    assert transcribe.entry_cached_ts(d, {"cached_date": "garbage"}) == 1_500_000_000


def test_upgrade_meta_v0_to_v1(tmp_path):
    d, meta = _v0_entry(tmp_path)
    os.utime(d / "meta.json", (1_500_000_000, 1_500_000_000))
    new = transcribe.upgrade_meta(d, meta)
    assert new["schema_version"] == 1
    assert new["files"] == {"transcript": "transcript.txt", "segments": "segments.json"}
    assert new["transcript_path"] == str(d / "transcript.txt")
    assert new["segments_path"] == str(d / "segments.json")
    assert datetime.fromisoformat(new["cached_date"]).timestamp() == 1_500_000_000
    assert new["title"] == "T" and new["language"] == "zh"
    assert meta["transcript_path"] == "/old/place/transcript.txt"  # input untouched


def test_upgrade_meta_drops_keys_whose_file_is_gone(tmp_path):
    d, meta = _v0_entry(tmp_path, files=("transcript.txt",))
    meta["audio_path"] = "/old/place/audio.mp3"  # user deleted the kept audio
    new = transcribe.upgrade_meta(d, meta)
    assert "audio_path" not in new


def test_upgrade_meta_never_adds_path_keys(tmp_path):
    """A transcript.srt rebuilt on a later hit must not grow a new stdout key."""
    d, meta = _v0_entry(tmp_path, files=("transcript.txt", "segments.json", "transcript.srt"))
    new = transcribe.upgrade_meta(d, meta)
    assert "srt_path" not in new
    assert new["files"]["srt"] == "transcript.srt"


def test_public_meta_hides_v1_keys_and_resolves_paths(tmp_path):
    d, meta = _v0_entry(tmp_path)
    new = transcribe.upgrade_meta(d, meta)
    out = transcribe.public_meta(d, new)
    assert not set(transcribe.V1_ONLY_KEYS) & set(out)
    assert set(out) == set(meta)
    assert out["transcript_path"] == str(d / "transcript.txt")


def test_needs_rewrite(tmp_path):
    d, meta = _v0_entry(tmp_path)
    assert transcribe._needs_rewrite(d, meta)  # v0
    new = transcribe.upgrade_meta(d, meta)
    assert not transcribe._needs_rewrite(d, new)
    moved = {**new, "transcript_path": "/elsewhere/transcript.txt"}
    assert transcribe._needs_rewrite(d, moved)


def _install(tmp_path, monkeypatch, meta_root):
    """A v0 entry for a local-file source, meta pointing at meta_root."""
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    clip = tmp_path / "clip.mp3"
    clip.write_bytes(b"fake-audio")
    key = transcribe.cache_key(str(clip))
    d = tmp_path / "cache" / "audio-tldr" / key
    d.mkdir(parents=True)
    (d / "transcript.txt").write_text("NEW")
    (d / "segments.json").write_text(json.dumps([{"start": 0, "end": 1, "text": "NEW"}]))
    (d / "meta.json").write_text(json.dumps({
        "title": "clip", "source": str(clip), "language": "en", "backend": "mlx-whisper",
        "transcript_path": f"{meta_root}/transcript.txt",
        "segments_path": f"{meta_root}/segments.json"}))
    return clip, key, d


def _hit(clip, capsys, *extra):
    assert transcribe.main([str(clip), *extra]) == 0
    return json.loads(capsys.readouterr().out.strip().splitlines()[-1])


def test_moved_cache_hits_and_prints_the_new_location(tmp_path, monkeypatch, capsys):
    clip, key, d = _install(tmp_path, monkeypatch, tmp_path / "gone")
    out = _hit(clip, capsys)
    assert out["cache_hit"] is True
    assert out["transcript_path"] == str(d / "transcript.txt")


def test_copied_cache_reads_its_own_files_not_the_old_copy(tmp_path, monkeypatch, capsys):
    old = tmp_path / "old"
    old.mkdir()
    (old / "transcript.txt").write_text("OLD")
    clip, key, d = _install(tmp_path, monkeypatch, old)
    out = _hit(clip, capsys)
    assert Path(out["transcript_path"]).read_text() == "NEW"


def test_control_group_absolute_path_resolver_reads_the_old_copy(tmp_path, monkeypatch, capsys):
    """Proves the copied-cache test can fail: swap in v0.9.1's rule (trust the
    absolute path in meta.json) and the same scenario reads the stale copy."""
    old = tmp_path / "old"
    old.mkdir()
    (old / "transcript.txt").write_text("OLD")
    clip, key, d = _install(tmp_path, monkeypatch, old)
    def legacy_resolver(entry, name):
        meta = json.loads((entry / "meta.json").read_text())
        p = Path(meta.get(transcribe.PATH_KEYS[name], ""))
        return p if p.is_file() else None
    monkeypatch.setattr(transcribe, "resolve_entry_file", legacy_resolver)
    out = _hit(clip, capsys)
    assert Path(out["transcript_path"]).read_text() == "OLD"


def test_hit_upgrades_meta_keeps_mtime_and_is_ascii(tmp_path, monkeypatch, capsys):
    clip, key, d = _install(tmp_path, monkeypatch, tmp_path / "gone")
    meta_p = d / "meta.json"
    meta = json.loads(meta_p.read_text())
    meta["title"] = "股癌 EP703"
    meta_p.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    os.utime(meta_p, (1_500_000_000, 1_500_000_000))
    _hit(clip, capsys)
    raw = meta_p.read_bytes()
    raw.decode("ascii")  # v0.9.1 on Windows reads with the locale encoding
    new = json.loads(raw)
    assert new["schema_version"] == 1 and new["title"] == "股癌 EP703"
    assert abs(meta_p.stat().st_mtime - 1_500_000_000) <= 2


def test_second_hit_does_not_rewrite(tmp_path, monkeypatch, capsys):
    clip, key, d = _install(tmp_path, monkeypatch, tmp_path / "gone")
    _hit(clip, capsys)
    writes = []
    monkeypatch.setattr(transcribe, "_atomic_write_text", lambda *a, **k: writes.append(a))
    _hit(clip, capsys)
    assert writes == []


@pytest.mark.skipif(sys.platform == "win32", reason="symlinks need privileges on Windows")
def test_symlinked_cache_dir_does_not_rewrite_every_hit(tmp_path, monkeypatch, capsys):
    clip, key, d = _install(tmp_path, monkeypatch, tmp_path / "gone")
    _hit(clip, capsys)
    link = tmp_path / "link"
    link.symlink_to(tmp_path / "cache")
    monkeypatch.setenv("XDG_CACHE_HOME", str(link))
    writes = []
    monkeypatch.setattr(transcribe, "_atomic_write_text", lambda *a, **k: writes.append(a))
    _hit(clip, capsys)
    assert writes == []


def test_srt_rebuilt_from_segments_in_the_entry(tmp_path, monkeypatch, capsys):
    clip, key, d = _install(tmp_path, monkeypatch, tmp_path / "gone")
    out = _hit(clip, capsys, "--format", "srt")
    assert out["srt_path"] == str(d / "transcript.srt")
    assert "NEW" in (d / "transcript.srt").read_text()


def test_newer_schema_is_read_but_never_rewritten(tmp_path, monkeypatch, capsys):
    clip, key, d = _install(tmp_path, monkeypatch, tmp_path / "gone")
    meta = json.loads((d / "meta.json").read_text())
    meta["schema_version"] = 99
    (d / "meta.json").write_text(json.dumps(meta))
    before = (d / "meta.json").read_text()
    out = _hit(clip, capsys)
    assert out["cache_hit"] is True and (d / "meta.json").read_text() == before


def test_upgrade_write_failure_still_hits(tmp_path, monkeypatch, capsys):
    clip, key, d = _install(tmp_path, monkeypatch, tmp_path / "gone")
    def boom(*a, **k):
        raise OSError("read-only")
    monkeypatch.setattr(transcribe, "_atomic_write_text", boom)
    out = _hit(clip, capsys)
    assert out["cache_hit"] is True


def test_miss_writes_v1_and_prints_v0_9_1_keys(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    monkeypatch.setattr(transcribe, "detect_backend", lambda: "mlx-whisper")
    monkeypatch.setattr(transcribe, "_run_backend",
                        lambda b, a, l, m=None, want_segments=False: ("hello", 1.0, "en", None))
    clip = tmp_path / "c.mp3"
    clip.write_bytes(b"a")
    assert transcribe.main([str(clip)]) == 0
    out = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    out.pop("retention_notice", None)  # Task 5
    assert not set(transcribe.V1_ONLY_KEYS) & set(out)
    d = Path(out["transcript_path"]).parent
    meta = json.loads((d / "meta.json").read_bytes().decode("ascii"))
    assert meta["schema_version"] == 1 and meta["files"] == {"transcript": "transcript.txt"}


def _stub_miss(monkeypatch, segments=None):
    monkeypatch.setattr(transcribe, "detect_backend", lambda: "mlx-whisper")
    monkeypatch.setattr(transcribe, "_run_backend",
                        lambda b, a, l, m=None, want_segments=False: ("hello", 1.0, "en", segments))


def test_frames_only_meta_next_to_a_transcript_is_a_miss(tmp_path, monkeypatch, capsys):
    clip, key, d = _install(tmp_path, monkeypatch, tmp_path / "gone")
    (d / "meta.json").write_text(json.dumps({
        "source": str(clip), "title": "clip", "frames_only": True,
        "created": "2026-10-10T00:00:00"}, ensure_ascii=False))
    assert transcribe.load_cached(key) is None
    _stub_miss(monkeypatch)
    out = _hit(clip, capsys)
    assert out["cache_hit"] is False and "transcript_path" in out


def test_non_int_schema_version_is_a_miss(tmp_path, monkeypatch):
    clip, key, d = _install(tmp_path, monkeypatch, tmp_path / "gone")
    meta = json.loads((d / "meta.json").read_text())
    meta["schema_version"] = "x"
    (d / "meta.json").write_text(json.dumps(meta))
    assert transcribe.load_cached(key) is None


def test_keep_audio_note_checks_the_entry_not_meta(tmp_path, monkeypatch, capsys):
    clip, key, d = _install(tmp_path, monkeypatch, tmp_path / "gone")
    meta = json.loads((d / "meta.json").read_text())
    meta["audio_path"] = "/somewhere/else.mp3"
    (d / "meta.json").write_text(json.dumps(meta))
    assert transcribe.main([str(clip), "--keep-audio"]) == 0
    assert "--keep-audio ignored" in capsys.readouterr().err


def test_segments_json_is_pure_ascii(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    _stub_miss(monkeypatch, [{"start": 0, "end": 1, "text": "股癌"}])
    clip = tmp_path / "c.mp3"
    clip.write_bytes(b"a")
    out = _hit(clip, capsys, "--format", "srt")
    raw = (Path(out["transcript_path"]).parent / "segments.json").read_bytes()
    assert json.loads(raw.decode("ascii"))[0]["text"] == "股癌"


def test_cache_text_files_are_utf8_and_context_is_ascii(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    monkeypatch.setattr(transcribe, "detect_backend", lambda: "mlx-whisper")
    monkeypatch.setattr(
        transcribe, "_run_backend",
        lambda b, a, l, m=None, want_segments=False: (
            "股癌", 1.0, "zh", [{"start": 0, "end": 1, "text": "股癌"}]))
    clip = tmp_path / "c.mp3"
    clip.write_bytes(b"a")
    out = _hit(clip, capsys, "--format", "srt")
    d = Path(out["transcript_path"]).parent
    assert "股癌" in (d / "transcript.txt").read_bytes().decode("utf-8")
    assert "股癌" in (d / "transcript.srt").read_bytes().decode("utf-8")
    transcribe.write_context(d, {"title": "股癌"})
    assert json.loads((d / "context.json").read_bytes().decode("ascii"))["title"] == "股癌"


def test_old_locale_encoded_context_json_is_still_read(tmp_path, monkeypatch):
    d = tmp_path / "entry"
    d.mkdir()
    (d / "context.json").write_bytes(
        json.dumps({"title": "股癌"}, ensure_ascii=False).encode("cp950"))
    _stub_locale(monkeypatch, "cp950")
    assert transcribe._read_context_file(d) == {"title": "股癌"}


import time as _time


def _entry_with_cached_date(tmp_path, monkeypatch, name, cached_epoch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    d = tmp_path / "audio-tldr" / name
    d.mkdir(parents=True)
    (d / "transcript.txt").write_text("x")
    (d / "meta.json").write_text(json.dumps({
        "schema_version": 1, "title": name, "source": f"https://x.test/{name}",
        "transcript_path": str(d / "transcript.txt"),
        "cached_date": datetime.fromtimestamp(cached_epoch, timezone.utc).isoformat()}))
    return d


def test_retention_uses_cached_date_not_mtime(tmp_path, monkeypatch):
    old = _entry_with_cached_date(tmp_path, monkeypatch, "old", _time.time() - 40 * 86400)
    fresh = _entry_with_cached_date(tmp_path, monkeypatch, "fresh", _time.time())
    os.utime(fresh / "meta.json", (0, 0))  # an ancient mtime must not matter
    transcribe.save_config({"retention_days": 30})
    assert transcribe.prune_expired() == 1
    assert not old.exists() and fresh.exists()


def test_cache_info_date_comes_from_cached_date(tmp_path, monkeypatch, capsys):
    stamp = datetime(2026, 1, 2, 3, 4, tzinfo=timezone.utc).timestamp()
    d = _entry_with_cached_date(tmp_path, monkeypatch, "e1", stamp)
    os.utime(d / "meta.json", (0, 0))
    assert transcribe.main(["--cache-info"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["entries"][0]["cached_date"] == \
        datetime.fromtimestamp(stamp).strftime("%Y-%m-%d %H:%M")


def test_prune_removes_stale_temp_files_only(tmp_path, monkeypatch, capsys):
    d = _entry_with_cached_date(tmp_path, monkeypatch, "e1", _time.time())
    stale = d / ".meta.json.tmp-123"
    stale.write_text("x")
    os.utime(stale, (0, 0))
    recent = d / ".meta.json.tmp-456"
    recent.write_text("x")
    transcribe.main(["--cache-info"])  # read-only command: must not delete
    assert stale.exists()
    transcribe.prune_expired()
    assert not stale.exists() and recent.exists()


def test_save_config_is_atomic_and_load_tolerates_corruption(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    transcribe.save_config({"retention_days": 7})
    assert transcribe.load_config() == {"retention_days": 7}
    transcribe.config_path().write_text("{half")
    assert transcribe.load_config() == {}


def test_frames_only_meta_is_v1(tmp_path):
    fspec = importlib.util.spec_from_file_location(
        "frames_cache", SCRIPT.parent / "frames.py")
    frames = importlib.util.module_from_spec(fspec)
    fspec.loader.exec_module(frames)
    frames.write_min_meta(tmp_path, "https://x", "片名")
    raw = (tmp_path / "meta.json").read_bytes()
    raw.decode("ascii")
    meta = json.loads(raw)
    assert meta["schema_version"] == 1 and meta["frames_only"] is True
    assert meta["files"] == {} and "created" in meta and "cached_date" in meta


def _stub_miss_clip(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    monkeypatch.setattr(transcribe, "detect_backend", lambda: "mlx-whisper")
    monkeypatch.setattr(transcribe, "_run_backend",
                        lambda b, a, l, m=None, want_segments=False: ("hello", 1.0, "en", None))
    clip = tmp_path / "c.mp3"
    clip.write_bytes(b"a")
    return clip


def test_notice_until_acknowledged(tmp_path, monkeypatch, capsys):
    clip = _stub_miss_clip(tmp_path, monkeypatch)
    out = _hit(clip, capsys)
    assert out["retention_notice"] == {
        "cache_dir": str(tmp_path / "audio-tldr"), "retention_days": None}
    assert transcribe.main(["--ack-retention-notice"]) == 0
    capsys.readouterr()
    assert "retention_notice" not in _hit(clip, capsys)  # now a cache hit


def test_set_retention_also_acknowledges(tmp_path, monkeypatch, capsys):
    clip = _stub_miss_clip(tmp_path, monkeypatch)
    assert transcribe.main(["--set-retention", "30"]) == 0
    capsys.readouterr()
    assert "retention_notice" not in _hit(clip, capsys)


def test_ack_refuses_to_overwrite_a_corrupt_config(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    transcribe.config_path().parent.mkdir(parents=True)
    transcribe.config_path().write_text('{"retention_days": 30')  # truncated
    assert transcribe.main(["--ack-retention-notice"]) == 2
    assert transcribe.config_path().read_text() == '{"retention_days": 30'


FIXTURE = Path(__file__).parent / "fixtures" / "cache_v0_9_1"


def install_fixture(tmp_path):
    key = (FIXTURE / "key.txt").read_text().strip()
    d = tmp_path / "audio-tldr" / key
    shutil.copytree(FIXTURE / "entry", d)
    return FIXTURE / "clip.mp3", key, d


def test_real_v0_9_1_entry_hits_and_upgrades(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    clip, key, d = install_fixture(tmp_path)
    assert transcribe.cache_key(str(clip)) == key
    before = os.stat(d / "meta.json").st_mtime
    out = _hit(clip, capsys, "--format", "srt")
    assert out["cache_hit"] is True
    assert Path(out["transcript_path"]) == d / "transcript.txt"
    assert json.loads((d / "meta.json").read_text())["schema_version"] == 1
    assert abs(os.stat(d / "meta.json").st_mtime - before) <= 2


def test_hit_output_keys_match_v0_9_1(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    transcribe.save_config({"retention_notice_shown": True})
    clip, key, d = install_fixture(tmp_path)
    out = _hit(clip, capsys, "--format", "srt")
    legacy = json.loads((FIXTURE / "v0_9_1_hit_output.json").read_text())
    assert set(out) == set(legacy)


def test_force_removes_correction_files(tmp_path, monkeypatch):
    d = tmp_path / "e"
    d.mkdir()
    for name in transcribe.DERIVED_FILES:
        transcribe.derived_file(d, name).write_text("x", encoding="utf-8")
    transcribe.remove_correction_files(d)
    gone = [n for n in transcribe.DERIVED_FILES if n not in transcribe.KEPT_ON_RETRANSCRIBE]
    assert gone and not any(transcribe.derived_file(d, n).exists() for n in gone)
    assert transcribe.KEPT_ON_RETRANSCRIBE == {"usage"}
    assert transcribe.derived_file(d, "usage").exists()


def test_remove_correction_files_survives_permission_error(tmp_path, monkeypatch, capsys):
    d = tmp_path / "e"
    d.mkdir()
    (d / "reference.md").write_text("x")
    def boom(self, *a, **k):
        raise PermissionError("denied")
    monkeypatch.setattr(Path, "unlink", boom)
    transcribe.remove_correction_files(d)  # must not raise
    assert "warning" in capsys.readouterr().err


def test_derived_files_never_enter_meta_files():
    assert not set(transcribe.DERIVED_FILES) & set(transcribe.ENTRY_FILES)


def test_correction_does_not_change_meta_files_or_hit_keys(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    monkeypatch.setenv("AUDIO_TLDR_GLOSSARY", str(tmp_path / "none.txt"))
    transcribe.save_config({"retention_notice_shown": True})
    clip, key, d = install_fixture(tmp_path)
    before = _hit(clip, capsys, "--format", "srt")
    meta_before = json.loads((d / "meta.json").read_text())
    spec_c = importlib.util.spec_from_file_location("correct_smoke", SCRIPT.parent / "correct.py")
    correct = importlib.util.module_from_spec(spec_c)
    spec_c.loader.exec_module(correct)
    assert correct.main(["check", str(d)]) == 0
    capsys.readouterr()
    edits = tmp_path / "edits.json"
    edits.write_text(json.dumps([{"wrong": "史記", "right": "事記", "before": "第一章 ",
                                  "after": "第一", "scope": "once"}]), encoding="utf-8")
    original = (d / "transcript.txt").read_bytes()
    assert correct.main(["apply", str(d), "--edits", str(edits), "--model", "sonnet"]) == 0
    applied = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert applied["accepted"] == 1
    assert "事記" in Path(applied["corrected_path"]).read_text(encoding="utf-8")
    assert (d / "transcript.txt").read_bytes() == original
    after = _hit(clip, capsys, "--format", "srt")
    assert after["transcript_path"].endswith("transcript.txt")
    assert set(after) == set(before)
    assert json.loads((d / "meta.json").read_text())["files"] == meta_before["files"]


LEGACY = os.environ.get("AUDIO_TLDR_LEGACY_SCRIPTS")


@pytest.mark.skipif(not LEGACY, reason="release.py sets AUDIO_TLDR_LEGACY_SCRIPTS to v0.9.1's scripts")
def test_v0_9_1_still_hits_an_entry_upgraded_by_1_x(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    clip, key, d = install_fixture(tmp_path)
    (d / "transcript.txt").write_text("嗯" * 900, encoding="utf-8")  # make 1.x rewrite it
    _hit(clip, capsys, "--format", "srt")  # upgrade with 1.x
    assert "\n" in (d / "transcript.txt").read_text(encoding="utf-8")
    assert json.loads((d / "meta.json").read_text())["schema_version"] == 1
    env = {**os.environ, "XDG_CACHE_HOME": str(tmp_path), "AUDIO_TLDR_REEXECED": "1"}
    proc = subprocess.run(
        [sys.executable, str(Path(LEGACY) / "transcribe.py"), str(clip), "--format", "srt"],
        env=env, capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout.strip().splitlines()[-1])
    legacy = json.loads((FIXTURE / "v0_9_1_hit_output.json").read_text())
    assert out["cache_hit"] is True
    # it must have read this test's cache, not a leftover copy elsewhere
    assert Path(out["transcript_path"]).resolve().is_relative_to(tmp_path.resolve())
    # v0.9.1 prints meta as-is, so it also shows the keys 1.x added; nothing
    # it printed before may be missing.
    assert set(out) == set(legacy) | set(transcribe.V1_ONLY_KEYS)


def _stub_locale(monkeypatch, preferred, getenc=None):
    monkeypatch.setattr(locale, "getpreferredencoding", lambda do_setlocale=True: preferred)
    if hasattr(locale, "getencoding") or getenc is not None:
        monkeypatch.setattr(locale, "getencoding", lambda: getenc or preferred, raising=False)


def test_digest_reads_utf8_transcript_and_instructions_under_cp950(tmp_path, monkeypatch, capsys):
    digest_spec = importlib.util.spec_from_file_location(
        "digest_cache", SCRIPT.parent / "digest.py")
    digest = importlib.util.module_from_spec(digest_spec)
    digest_spec.loader.exec_module(digest)
    _stub_locale(monkeypatch, "cp950")
    # Path.read_text() with no encoding uses the C-level locale, which a stub
    # of locale.* cannot reach; make it behave as a cp950 Windows would
    real_read_text = Path.read_text

    def cp950_read_text(self, encoding=None, errors=None):
        return real_read_text(self, encoding=encoding or "cp950", errors=errors)

    monkeypatch.setattr(Path, "read_text", cp950_read_text)
    text = "今天討論摘要，「測試」——完成。"
    t = tmp_path / "t.txt"
    t.write_bytes(text.encode("utf-8"))
    ins = tmp_path / "ins.txt"
    ins.write_bytes("請用繁體中文摘要。".encode("utf-8"))
    seen = {}

    def fake_chat(host, model, messages, timeout=None, **kw):
        seen["messages"] = messages
        return "ok"

    monkeypatch.setattr(digest, "call_ollama_chat", fake_chat)
    monkeypatch.setattr(sys, "argv", ["digest.py", str(t), "--model", "x",
                                      "--instructions-file", str(ins)])
    assert digest.main() == 0
    blob = json.dumps(seen["messages"], ensure_ascii=False)
    assert text in blob
    assert "請用繁體中文摘要。" in blob


def test_load_config_reads_a_bom_config(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    p = transcribe.config_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"\xef\xbb\xbf" + json.dumps({"k": "v"}).encode("utf-8"))
    assert transcribe.load_config() == {"k": "v"}


def test_read_json_falls_back_to_system_code_page_in_utf8_mode(tmp_path, monkeypatch):
    # Python 3.15 UTF-8 mode: getpreferredencoding says utf-8, getencoding still
    # reports the ANSI code page the 0.9.x file was written with
    _stub_locale(monkeypatch, "utf-8", getenc="cp950")
    p = tmp_path / "meta.json"
    p.write_bytes(json.dumps({"title": "測試"}, ensure_ascii=False).encode("cp950"))
    assert transcribe._read_json(p) == {"title": "測試"}


@pytest.mark.skipif(not LEGACY, reason="release.py sets AUDIO_TLDR_LEGACY_SCRIPTS to v0.9.1's scripts")
def test_v0_9_1_still_hits_an_entry_with_correction_files(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    clip, key, d = install_fixture(tmp_path)
    _hit(clip, capsys, "--format", "srt")
    for name in transcribe.DERIVED_FILES:
        transcribe.derived_file(d, name).write_text("{}" if name == "corrections" else "x", encoding="utf-8")
    env = {**os.environ, "XDG_CACHE_HOME": str(tmp_path), "AUDIO_TLDR_REEXECED": "1"}
    proc = subprocess.run(
        [sys.executable, str(Path(LEGACY) / "transcribe.py"), str(clip), "--format", "srt"],
        env=env, capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout.strip().splitlines()[-1])
    assert out["cache_hit"] is True and out["transcript_path"].endswith("transcript.txt")


def test_miss_writes_one_segment_per_line_without_subtitle(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    seen = {}

    def backend(b, a, l, m=None, want_segments=False):
        seen["want_segments"] = want_segments
        return ("第一段。第二段。", 2.0, "zh",
                [{"start": 0, "end": 1, "text": "第一段。"}, {"start": 1, "end": 2, "text": "第二段。"}])
    monkeypatch.setattr(transcribe, "detect_backend", lambda: "mlx-whisper")
    monkeypatch.setattr(transcribe, "_run_backend", backend)
    clip = tmp_path / "c.mp3"
    clip.write_bytes(b"a")
    assert transcribe.main([str(clip)]) == 0
    out = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    d = Path(out["transcript_path"]).parent
    assert seen["want_segments"] is True  # mlx-whisper: segments are free, always asked for
    assert (d / "transcript.txt").read_text(encoding="utf-8") == "第一段。\n第二段。"
    assert not (d / "segments.json").exists()  # only written when a subtitle was asked for


def test_whisper_cpp_is_not_asked_for_segments_without_subtitle(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    seen = {}

    def backend(b, a, l, m=None, want_segments=False):
        seen["want_segments"] = want_segments
        return ("一行。\n二行。", 2.0, "zh", None)
    monkeypatch.setattr(transcribe, "detect_backend", lambda: "whisper-cpp")
    monkeypatch.setattr(transcribe, "_run_backend", backend)
    monkeypatch.setenv("AUDIO_TLDR_WHISPER_CPP_MODEL", str(tmp_path / "m.bin"))
    clip = tmp_path / "c.mp3"
    clip.write_bytes(b"a")
    assert transcribe.main([str(clip)]) == 0
    assert seen["want_segments"] is False


LONG_ZH = "嗯" * 300 + "。" + "啊" * 300 + "。"


def test_hit_upgrades_single_line_transcript_insert_only_and_keeps_mtime(tmp_path, monkeypatch, capsys):
    clip, key, d = _install(tmp_path, monkeypatch, tmp_path / "gone")
    t = d / "transcript.txt"
    t.write_text(LONG_ZH, encoding="utf-8")
    (d / "segments.json").write_text(json.dumps([{"start": 0, "end": 1, "text": "嗯" * 300 + "。"},
                                                 {"start": 1, "end": 2, "text": "啊" * 300 + "。"}]))
    os.utime(t, (1_500_000_000, 1_500_000_000))
    _hit(clip, capsys)
    new = t.read_bytes().decode("utf-8")
    assert new == "嗯" * 300 + "。\n" + "啊" * 300 + "。"
    assert abs(t.stat().st_mtime - 1_500_000_000) <= 2


def test_upgrade_keeps_crlf_bytes(tmp_path, monkeypatch, capsys):
    clip, key, d = _install(tmp_path, monkeypatch, tmp_path / "gone")
    t = d / "transcript.txt"
    t.write_bytes(("開頭\r\n" + "嗯" * 900).encode("utf-8"))
    _hit(clip, capsys)
    raw = t.read_bytes()
    assert b"\r\r" not in raw and raw.startswith("開頭\r\n".encode("utf-8"))
    assert transcribe.strip_breaks(raw.decode("utf-8")) == "開頭" + "嗯" * 900


def test_upgrade_gives_up_when_the_file_changed_meanwhile(tmp_path, monkeypatch, capsys):
    clip, key, d = _install(tmp_path, monkeypatch, tmp_path / "gone")
    t = d / "transcript.txt"
    t.write_text("嗯" * 900, encoding="utf-8")
    real = transcribe.wrap_lines

    def racing_wrap(text, *a, **k):
        t.write_text("NEW TRANSCRIPT FROM --force", encoding="utf-8")  # another process re-transcribed
        return real(text, *a, **k)
    monkeypatch.setattr(transcribe, "wrap_lines", racing_wrap)
    _hit(clip, capsys)
    assert t.read_text(encoding="utf-8") == "NEW TRANSCRIPT FROM --force"


def test_upgrade_skips_newer_schema(tmp_path, monkeypatch, capsys):
    clip, key, d = _install(tmp_path, monkeypatch, tmp_path / "gone")
    t = d / "transcript.txt"
    t.write_text("嗯" * 900, encoding="utf-8")
    meta = json.loads((d / "meta.json").read_text())
    meta["schema_version"] = transcribe.SCHEMA_VERSION + 1
    (d / "meta.json").write_text(json.dumps(meta))
    _hit(clip, capsys)
    assert "\n" not in t.read_text(encoding="utf-8")


def test_upgrade_failure_still_hits(tmp_path, monkeypatch, capsys):
    clip, key, d = _install(tmp_path, monkeypatch, tmp_path / "gone")
    (d / "transcript.txt").write_text("嗯" * 900, encoding="utf-8")
    real = transcribe._atomic_write_text

    def boom(path, *a, **k):
        if path.name == "transcript.txt":
            raise OSError("disk full")
        return real(path, *a, **k)
    monkeypatch.setattr(transcribe, "_atomic_write_text", boom)
    out = _hit(clip, capsys)
    assert out["cache_hit"] is True
    assert "\n" not in (d / "transcript.txt").read_text(encoding="utf-8")


def test_upgraded_hit_output_keys_still_match_v0_9_1(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    transcribe.save_config({"retention_notice_shown": True})
    clip, key, d = install_fixture(tmp_path)
    (d / "transcript.txt").write_text("嗯" * 900, encoding="utf-8")
    out = _hit(clip, capsys, "--format", "srt")
    legacy = json.loads((FIXTURE / "v0_9_1_hit_output.json").read_text())
    assert set(out) == set(legacy) and "\n" in (d / "transcript.txt").read_text(encoding="utf-8")


def test_upgrade_leaves_short_and_multiline_untouched_and_is_idempotent(tmp_path, monkeypatch, capsys):
    clip, key, d = _install(tmp_path, monkeypatch, tmp_path / "gone")
    t = d / "transcript.txt"
    t.write_bytes("短稿\n第二行".encode("utf-8"))
    before = t.read_bytes()
    _hit(clip, capsys)
    assert t.read_bytes() == before
    t.write_text(LONG_ZH, encoding="utf-8")
    os.utime(t, (1_500_000_000, 1_500_000_000))
    _hit(clip, capsys)
    after = t.read_bytes()
    assert b"\n" in after
    mt = t.stat().st_mtime_ns
    _hit(clip, capsys)
    assert t.read_bytes() == after and t.stat().st_mtime_ns == mt


def test_upgrade_leaves_bom_file_bytes_alone(tmp_path, monkeypatch, capsys):
    clip, key, d = _install(tmp_path, monkeypatch, tmp_path / "gone")
    t = d / "transcript.txt"
    raw = b"\xef\xbb\xbf" + ("嗯" * 900).encode("utf-8")
    t.write_bytes(raw)
    out = _hit(clip, capsys)
    assert out["cache_hit"] is True and t.read_bytes() == raw


def test_upgrade_leaves_legacy_code_page_file_alone(tmp_path, monkeypatch, capsys):
    clip, key, d = _install(tmp_path, monkeypatch, tmp_path / "gone")
    t = d / "transcript.txt"
    raw = ("嗯" * 900).encode("cp950")
    t.write_bytes(raw)
    out = _hit(clip, capsys)
    assert out["cache_hit"] is True and t.read_bytes() == raw


def test_upgrade_malformed_segments_still_hits_with_a_note(tmp_path, monkeypatch, capsys):
    clip, key, d = _install(tmp_path, monkeypatch, tmp_path / "gone")
    t = d / "transcript.txt"
    t.write_text("嗯" * 900, encoding="utf-8")
    (d / "segments.json").write_text(json.dumps([{"text": 5}]))
    assert transcribe.main([str(clip)]) == 0
    cap = capsys.readouterr()
    assert json.loads(cap.out.strip().splitlines()[-1])["cache_hit"] is True
    assert "note: could not add line breaks" in cap.err
    assert t.read_text(encoding="utf-8") == "嗯" * 900
