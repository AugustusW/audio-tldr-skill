"""Unit tests for the release helper.

Everything here is a pure string transformation. The parts of `release.py` that
touch git, GitHub or the filesystem are deliberately not exercised: they are a
thin shell over subprocess calls, and mocking them would only assert that the
mocks were called.
"""
import pytest

from scripts import release


PLUGIN_JSON = """{
  "name": "audio-tldr",
  "description": "Summarize videos.",
  "version": "0.7.3",
  "license": "MIT"
}"""

CHANGELOG = """# Changelog

Preamble that mentions [0.0.1] and should never be mistaken for an entry.

## [0.7.3] - 2026-09-01

### Added

- The newest thing.

## [0.7.2] - 2026-09-01

### Fixed

- The older thing.
"""

README_EN = """## Develop

python3 -m pytest tests/   # 160 unit tests, no network or model needed

## Status

v0.7.3 ([CHANGELOG](./CHANGELOG.md)) - core logic is covered by 160 offline unit tests.
Frame extraction (v0.5.0) is stubbed. The behavior fixed in v0.7.1 was measured against ffmpeg.
"""

README_ZH = """## 開發

python3 -m pytest tests/   # 160 個單元測試，不需網路或模型

## 狀態

v0.7.3（[CHANGELOG](./CHANGELOG.md)）核心邏輯有 160 個離線單元測試。
影格擷取（v0.5.0）以 stub 取代。v0.7.1 修正的行為是對 ffmpeg 8.1 量測的。
"""


class TestParseVersion:
    @pytest.mark.parametrize("raw", ["0.7.4", "1.0.0", "10.20.30"])
    def test_accepts_plain_triples(self, raw):
        assert release.format_version(release.parse_version(raw)) == raw

    @pytest.mark.parametrize("raw", ["v0.7.4", "0.7", "0.7.4.1", "a.b.c", "", "0.7.4-rc1"])
    def test_rejects_anything_else(self, raw):
        with pytest.raises(ValueError):
            release.parse_version(raw)

    def test_leading_v_is_rejected_rather_than_stripped(self):
        # The tag carries the v; the manifests must not. Silently accepting
        # "v0.7.4" here would write "v0.7.4" into plugin.json.
        with pytest.raises(ValueError):
            release.parse_version("v0.7.4")


class TestSetJsonVersion:
    def test_replaces_the_version_and_nothing_else(self):
        out = release.set_json_version(PLUGIN_JSON, "0.7.4")
        assert '"version": "0.7.4"' in out
        assert '"version": "0.7.3"' not in out
        assert '"name": "audio-tldr"' in out
        assert '"license": "MIT"' in out

    def test_refuses_when_no_version_field_is_present(self):
        with pytest.raises(ValueError):
            release.set_json_version('{"name": "x"}', "0.7.4")


class TestChangelog:
    def test_newest_entry_is_the_first_heading_not_the_preamble(self):
        assert release.newest_changelog_version(CHANGELOG) == "0.7.3"

    def test_newest_entry_of_an_empty_changelog_is_none(self):
        assert release.newest_changelog_version("# Changelog\n") is None

    def test_section_stops_at_the_next_entry(self):
        body = release.changelog_section(CHANGELOG, "0.7.3")
        assert "The newest thing." in body
        assert "The older thing." not in body
        assert not body.startswith("## [")

    def test_section_of_a_missing_version_raises(self):
        with pytest.raises(ValueError):
            release.changelog_section(CHANGELOG, "9.9.9")


class TestReadmeStatusVersion:
    @pytest.mark.parametrize("text", [README_EN, README_ZH])
    def test_updates_the_status_version(self, text):
        out = release.set_status_version(text, "0.7.4")
        assert release.stated_status_version(out) == "0.7.4"

    @pytest.mark.parametrize("text", [README_EN, README_ZH])
    def test_leaves_historical_version_mentions_alone(self, text):
        # These say when a feature shipped. A release must not rewrite them.
        out = release.set_status_version(text, "0.7.4")
        assert "v0.5.0" in out
        assert "v0.7.1" in out

    def test_duplicate_status_lines_are_an_error_not_first_wins(self):
        # A stale leftover Status line after the real one: first-wins reading
        # stayed green on the first and count=1 writing never touched the
        # second, so the stale line lived forever (sepia issue #39 shape,
        # reproduced against this repo before fixing).
        text = README_EN + "\nv0.6.0 ([CHANGELOG](./CHANGELOG.md)) stale leftover\n"
        with pytest.raises(ValueError):
            release.stated_status_version(text)
        with pytest.raises(ValueError):
            release.set_status_version(text, "0.7.4")

    def test_refuses_a_readme_with_no_status_version(self):
        with pytest.raises(ValueError):
            release.set_status_version("## Status\n\nNo version here.\n", "0.7.4")


class TestReadmeTestCounts:
    def test_updates_every_stated_count_in_english(self):
        out = release.set_test_counts(README_EN, 171, "en")
        assert release.stated_test_counts(out, "en") == [171, 171]
        assert "160" not in out

    def test_updates_every_stated_count_in_chinese(self):
        out = release.set_test_counts(README_ZH, 171, "zh")
        assert release.stated_test_counts(out, "zh") == [171, 171]
        assert "160" not in out

    def test_refuses_when_the_readme_states_no_count(self):
        with pytest.raises(ValueError):
            release.set_test_counts("## Status\n\nNothing.\n", 171, "en")


class TestGuards:
    def test_the_new_version_must_be_higher(self):
        assert release.is_newer("0.7.4", "0.7.3")
        assert release.is_newer("0.8.0", "0.7.9")
        assert release.is_newer("1.0.0", "0.9.9")

    @pytest.mark.parametrize("new,cur", [("0.7.3", "0.7.3"), ("0.7.2", "0.7.3"), ("0.6.9", "0.7.0")])
    def test_same_or_lower_is_not_newer(self, new, cur):
        assert not release.is_newer(new, cur)
