"""The release checklist, enforced.

The checklist in README's Versioning section and at the top of CHANGELOG.md is
correct, and it still got missed: v0.7.2 shipped with both READMEs claiming
v0.7.1 and 149 tests while the suite had grown to 154. A checklist has no red
light, so these numbers drift silently and the Status section, whose whole job
is to say honestly what has been verified, is the part that goes stale.

These tests are that red light. They read the numbers out of the docs and
compare them against the repository itself, so a release that forgets one of
them cannot go green.

Where those numbers live is defined once, in `scripts/release.py`, and imported
here. The script writes them and this file checks them, so they cannot disagree
about what they are looking at.

That sharing has a cost worth naming: a pattern that matched the wrong line
would be written to and read from the same wrong line, and these tests would
stay green. The independent check is `tests/test_release.py`, which asserts the
same patterns against fixtures with known-correct answers instead of against
the repository. Neither file alone is enough.
"""
import json

import pytest

from scripts import release


READMES = sorted(release.READMES.items(), key=lambda kv: kv[1])
README_IDS = [lang for _, lang in READMES]


def test_marketplace_version_matches_plugin():
    marketplace = json.loads(release.read(release.MARKETPLACE_JSON))
    versions = {plugin["version"] for plugin in marketplace["plugins"]}
    expected = release.plugin_version()
    assert versions == {expected}, (
        "marketplace.json and plugin.json must carry the same version; "
        f"marketplace has {sorted(versions)}, plugin.json has {expected}"
    )


def test_changelog_newest_entry_matches_plugin_version():
    newest = release.newest_changelog_version(release.read(release.CHANGELOG))
    expected = release.plugin_version()
    assert newest, "CHANGELOG.md has no '## [x.y.z]' entries"
    assert newest == expected, (
        f"the newest CHANGELOG entry is {newest} but plugin.json says {expected}; "
        "every release adds an entry"
    )


@pytest.mark.parametrize("readme,lang", READMES, ids=README_IDS)
def test_readme_status_version_matches_plugin_version(readme, lang):
    stated = release.stated_status_version(release.read(readme))
    expected = release.plugin_version()
    assert stated, f"{readme.name} has no 'vX.Y.Z ([CHANGELOG]...)' in its Status section"
    assert stated == expected, (
        f"{readme.name} Status says v{stated} but plugin.json says {expected}"
    )


@pytest.mark.parametrize("readme,lang", READMES, ids=README_IDS)
def test_readme_test_counts_match_the_suite(readme, lang):
    stated = release.stated_test_counts(release.read(readme), lang)
    assert stated, f"{readme.name} states no test count"
    collected = release.collected_test_count()
    wrong = sorted({n for n in stated if n != collected})
    assert not wrong, (
        f"{readme.name} states {wrong} test(s) but the suite collects {collected}; "
        "update every count in the file"
    )
