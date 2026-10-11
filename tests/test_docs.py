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

ROOT = release.ROOT


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


SKILL_MD = release.ROOT / "skills" / "audio-tldr" / "SKILL.md"
REPO_URL = "https://github.com/AugustusW/audio-tldr-skill"


def test_skill_md_names_its_source_near_the_top():
    """The skill is also distributed as a bare zip (e.g. on a marketplace),
    where SKILL.md is the only file an agent reads; the README is not there
    to say where the project lives."""
    head = "\n".join(release.read(SKILL_MD).splitlines()[:15])
    assert REPO_URL in head


def test_skill_md_points_feedback_to_github_issues():
    text = release.read(SKILL_MD)
    assert "## Feedback" in text
    feedback = text.split("## Feedback", 1)[1]
    assert f"{REPO_URL}/issues" in feedback


def test_security_md_supported_version_matches_plugin_version():
    stated = release.stated_security_series(release.read(release.SECURITY_MD))
    expected = release.supported_series(release.plugin_version())
    assert stated == expected, (
        f"SECURITY.md supports {stated}.x but the current release is "
        f"{release.plugin_version()}; the supported row must be {expected}.x"
    )


def test_skill_documents_the_correction_phase():
    t = (ROOT / "skills" / "audio-tldr" / "SKILL.md").read_text(encoding="utf-8")
    for needle in ("## Phase 1.8 — Correct", 'correct.py" check', 'correct.py" apply',
                   'correct.py" subtitle', 'correct.py" ollama', "prompts/correct.md",
                   "corrected_path", '--edits "<that file>"', "unavailable"):
        assert needle in t, needle


def test_skill_passes_the_same_context_to_every_correct_call():
    t = (ROOT / "skills" / "audio-tldr" / "SKILL.md").read_text(encoding="utf-8")
    for sub in ("check", "apply", "subtitle", "ollama"):
        line = next(l for l in t.splitlines() if f'correct.py" {sub}' in l)
        assert '--context "<context_path>"' in line, sub


def test_readmes_document_transcript_correction():
    for name, needles in (("README.md", ("## Transcript correction", "pip install pypinyin jellyfish",
                                         "transcript.corrected.txt", "corrections.json", "usage.jsonl")),
                          ("README.zh-TW.md", ("## 逐字稿校正", "pip install pypinyin jellyfish",
                                               "transcript.corrected.txt", "corrections.json",
                                               "usage.jsonl"))):
        t = (ROOT / name).read_text(encoding="utf-8")
        for n in needles:
            assert n in t, (name, n)


def test_security_policy_covers_transcript_correction():
    t = (ROOT / "SECURITY.md").read_text(encoding="utf-8")
    assert "Transcript correction" in t and "untrusted" in t


def test_ci_installs_the_correction_packages():
    # .gitea/ and internal/ are not published; the GitHub tree runs this suite without them.
    workflows = [".github/workflows/ci.yml"]
    if (ROOT / ".gitea").is_dir():
        workflows.append(".gitea/workflows/ci.yml")
    for wf in workflows:
        t = (ROOT / wf).read_text(encoding="utf-8")
        assert '"pypinyin>=0.50"' in t and '"jellyfish>=1.0"' in t, wf


@pytest.mark.skipif(not (ROOT / "internal").is_dir(), reason="internal/ is not published")
def test_adr_0004_exists():
    assert (ROOT / "internal" / "adr" / "0004-derived-cache-files-are-recomputable.md").is_file()


def test_skill_md_long_transcript_instructions_are_doable():
    t = (ROOT / "skills" / "audio-tldr" / "SKILL.md").read_text(encoding="utf-8")
    assert "50k words" not in t and "--tail" in t and "--whole-text" in t and "offset" in t


def test_readmes_document_long_transcripts():
    for name, needles in (("README.md", ("AUDIO_TLDR_OLLAMA_NUM_CTX", "sections")),
                          ("README.zh-TW.md", ("AUDIO_TLDR_OLLAMA_NUM_CTX", "分段"))):
        t = (ROOT / name).read_text(encoding="utf-8")
        for n in needles:
            assert n in t, (name, n)


def test_security_policy_covers_section_notes():
    assert "section notes" in (ROOT / "SECURITY.md").read_text(encoding="utf-8").lower()
