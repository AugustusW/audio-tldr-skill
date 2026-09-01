"""The release checklist, enforced.

The checklist in README's Versioning section and at the top of CHANGELOG.md is
correct, and it still got missed: v0.7.2 shipped with both READMEs claiming
v0.7.1 and 149 tests while the suite had grown to 154. A checklist has no red
light, so these numbers drift silently and the Status section, whose whole job
is to say honestly what has been verified, is the part that goes stale.

These tests are that red light. They read the numbers out of the docs and
compare them against the repository itself, so a release that forgets one of
them cannot go green.
"""
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PLUGIN_JSON = ROOT / ".claude-plugin" / "plugin.json"
MARKETPLACE_JSON = ROOT / ".claude-plugin" / "marketplace.json"
CHANGELOG = ROOT / "CHANGELOG.md"
README_EN = ROOT / "README.md"
README_ZH = ROOT / "README.zh-TW.md"

# The Status heading opens with the current version linking to the CHANGELOG.
# Anchoring on that link keeps the historical "shipped in v0.5.0" mentions
# elsewhere in the same section out of the match.
STATUS_VERSION_RE = re.compile(r"v(\d+\.\d+\.\d+)\s*[（(]\[CHANGELOG\]")

# Every place either README states the size of the suite.
TEST_COUNT_RES = {
    README_EN: re.compile(r"(\d+)\s+(?:offline\s+)?unit tests"),
    README_ZH: re.compile(r"(\d+)\s*個(?:離線)?單元測試"),
}

CHANGELOG_ENTRY_RE = re.compile(r"^## \[(\d+\.\d+\.\d+)\]", re.M)


def _read(path):
    return path.read_text(encoding="utf-8")


def _plugin_version():
    return json.loads(_read(PLUGIN_JSON))["version"]


def _collected_test_count():
    """Ask pytest how many tests exist, rather than trusting a hardcoded number.

    --collect-only does not execute anything, so this cannot recurse. Running
    it against the tests directory rather than the invoking node makes the
    count the same whether the full suite or only this file was requested.
    """
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", str(ROOT / "tests")],
        capture_output=True,
        text=True,
        cwd=ROOT,
    )
    match = re.search(r"(\d+) tests? collected", proc.stdout)
    if not match:
        pytest.fail(
            "could not read a collected-test count from pytest:\n"
            f"stdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
        )
    return int(match.group(1))


def test_marketplace_version_matches_plugin():
    marketplace = json.loads(_read(MARKETPLACE_JSON))
    versions = {plugin["version"] for plugin in marketplace["plugins"]}
    assert versions == {_plugin_version()}, (
        "marketplace.json and plugin.json must carry the same version; "
        f"marketplace has {sorted(versions)}, plugin.json has {_plugin_version()}"
    )


def test_changelog_newest_entry_matches_plugin_version():
    entries = CHANGELOG_ENTRY_RE.findall(_read(CHANGELOG))
    assert entries, "CHANGELOG.md has no '## [x.y.z]' entries"
    assert entries[0] == _plugin_version(), (
        f"the newest CHANGELOG entry is {entries[0]} but plugin.json says "
        f"{_plugin_version()}; every release adds an entry"
    )


@pytest.mark.parametrize("readme", [README_EN, README_ZH], ids=["en", "zh-TW"])
def test_readme_status_version_matches_plugin_version(readme):
    found = STATUS_VERSION_RE.search(_read(readme))
    assert found, f"{readme.name} has no 'vX.Y.Z ([CHANGELOG]...)' in its Status section"
    assert found.group(1) == _plugin_version(), (
        f"{readme.name} Status says v{found.group(1)} but plugin.json says "
        f"{_plugin_version()}"
    )


@pytest.mark.parametrize("readme", [README_EN, README_ZH], ids=["en", "zh-TW"])
def test_readme_test_counts_match_the_suite(readme):
    stated = TEST_COUNT_RES[readme].findall(_read(readme))
    assert stated, f"{readme.name} states no test count"
    collected = _collected_test_count()
    wrong = sorted({int(n) for n in stated if int(n) != collected})
    assert not wrong, (
        f"{readme.name} states {wrong} test(s) but the suite collects "
        f"{collected}; update every count in the file"
    )
