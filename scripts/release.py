#!/usr/bin/env python3
"""Perform a release as one action, so that no step of it can be skipped.

The release checklist used to be prose in the README. It was accurate, and it
was skipped anyway: v0.7.2 shipped with both READMEs a version behind, and
neither v0.7.2 nor v0.7.3 got the git tag and GitHub Release the same checklist
asks for. The tag being missing was visible for weeks on an unrelated page that
reads the repository's latest release, and nobody was reading it.

`tests/test_docs.py` closed half of that: the version and test-count numbers in
the docs now fail the suite when they drift. It cannot see the other half,
because a tag and a Release live on GitHub, not in the working tree.

So this script owns the whole sequence. Write the CHANGELOG entry, run

    python3 scripts/release.py 0.7.4

and it bumps both manifests, rewrites the numbers in both READMEs, refuses to
continue unless the full suite passes, then commits, tags, pushes and publishes
the Release with that CHANGELOG section as the notes. Nothing to remember, so
nothing to forget.

This module is also the single definition of where those numbers live in the
docs. `tests/test_docs.py` imports the patterns from here rather than keeping
its own copy, because two copies of a rule are two rules that drift apart.
"""
import argparse
import io
import json
import os
import re
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGIN_JSON = ROOT / ".claude-plugin" / "plugin.json"
MARKETPLACE_JSON = ROOT / ".claude-plugin" / "marketplace.json"
# The OpenAI / Codex plugin directory reads its own manifest; it carries the same version.
CODEX_PLUGIN_JSON = ROOT / ".codex-plugin" / "plugin.json"
CHANGELOG = ROOT / "CHANGELOG.md"
README_EN = ROOT / "README.md"
README_ZH = ROOT / "README.zh-TW.md"
SECURITY_MD = ROOT / "SECURITY.md"

# The supported-versions row: "| latest `0.9.x`|" before 1.0, "| latest `1.x`|"
# after. Pre-1.0 every minor can break things, so the series is major.minor;
# from 1.0 on it is the major.
SECURITY_VERSION_RE = re.compile(r"(\|\s*latest\s+`)(\d+(?:\.\d+)?)(\.x`)")

# The version whose cache format 1.x promises to stay readable by (downgrade).
# Its scripts are exported from this tag and run against an entry 1.x upgraded.
LEGACY_TAG = "v0.9.1"
LEGACY_SCRIPTS = "skills/audio-tldr/scripts"

# Which language each README's sentences are in, for the test-count patterns.
READMES = {README_EN: "en", README_ZH: "zh"}

# The Status heading opens with the current version linking to the CHANGELOG.
# Anchoring on that link is what keeps the historical mentions in the same
# section ("Frame extraction (v0.5.0)", "fixed in v0.7.1") out of the match.
# Those record when a feature shipped and must survive a release untouched.
STATUS_VERSION_RE = re.compile(r"v(\d+\.\d+\.\d+)(\s*[（(]\[CHANGELOG\])")

# Every place a README states the size of the suite.
TEST_COUNT_RE = {
    "en": re.compile(r"(\d+)(\s+(?:offline\s+)?unit tests)"),
    "zh": re.compile(r"(\d+)(\s*個(?:離線)?單元測試)"),
}

CHANGELOG_ENTRY_RE = re.compile(r"^## \[(\d+\.\d+\.\d+)\]", re.M)

JSON_VERSION_RE = re.compile(r'("version":\s*")(\d+\.\d+\.\d+)(")')

VERSION_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")

# A release commit may carry an uncommitted CHANGELOG entry written just
# beforehand. Everything else must already be committed.
ALLOWED_DIRTY = {"CHANGELOG.md"}


# --- pure helpers -----------------------------------------------------------


def parse_version(raw):
    """Parse a bare X.Y.Z. A leading 'v' is rejected rather than stripped:
    the tag carries it, the manifests must not, and quietly accepting it here
    would write "v0.7.4" into plugin.json."""
    match = VERSION_RE.match(raw or "")
    if not match:
        raise ValueError(f"expected a bare X.Y.Z version, got {raw!r}")
    return tuple(int(p) for p in match.groups())


def format_version(parts):
    return ".".join(str(p) for p in parts)


def is_newer(new, current):
    return parse_version(new) > parse_version(current)


def set_json_version(text, version):
    if not JSON_VERSION_RE.search(text):
        raise ValueError("no \"version\": \"x.y.z\" field to update")
    return JSON_VERSION_RE.sub(lambda m: m.group(1) + version + m.group(3), text)


def newest_changelog_version(text):
    entries = CHANGELOG_ENTRY_RE.findall(text)
    return entries[0] if entries else None


def changelog_section(text, version):
    """The body under one entry, for use as the GitHub Release notes."""
    lines = text.splitlines()
    heading = f"## [{version}]"
    start = next((i + 1 for i, line in enumerate(lines) if line.startswith(heading)), None)
    if start is None:
        raise ValueError(f"CHANGELOG.md has no entry for {version}")
    end = next((j for j in range(start, len(lines)) if lines[j].startswith("## [")), len(lines))
    return "\n".join(lines[start:end]).strip()


def stated_status_version(text):
    """The Status version, requiring it to be stated exactly once. Two lines
    matching the pattern mean a stale duplicate that first-wins reading and
    count=1 writing would both keep alive forever (the same false green as
    sepia issue #39, confirmed empirically against this repository)."""
    matches = STATUS_VERSION_RE.findall(text)
    if len(matches) > 1:
        raise ValueError(
            f"{len(matches)} Status version lines found; a stale duplicate "
            "survives first-wins updates, keep exactly one"
        )
    return matches[0][0] if matches else None


def set_status_version(text, version):
    matches = STATUS_VERSION_RE.findall(text)
    if len(matches) != 1:
        raise ValueError(
            "expected exactly one 'vX.Y.Z ([CHANGELOG]...)' Status line, "
            f"found {len(matches)}"
        )
    return STATUS_VERSION_RE.sub(lambda m: "v" + version + m.group(2), text, count=1)


def stated_test_counts(text, lang):
    return [int(m.group(1)) for m in TEST_COUNT_RE[lang].finditer(text)]


def set_test_counts(text, count, lang):
    if not TEST_COUNT_RE[lang].search(text):
        raise ValueError("this README states no test count")
    return TEST_COUNT_RE[lang].sub(lambda m: str(count) + m.group(2), text)


# --- the shell around them --------------------------------------------------


def read(path):
    return path.read_text(encoding="utf-8")


def plugin_version():
    return json.loads(read(PLUGIN_JSON))["version"]


def collected_test_count():
    """Ask pytest how many tests exist, rather than trusting a written number.

    --collect-only does not execute anything, so this cannot recurse, and
    pointing it at the tests directory rather than at the invoking node makes
    the answer the same however the suite was started.
    """
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", str(ROOT / "tests")],
        capture_output=True, text=True, cwd=ROOT,
    )
    match = re.search(r"(\d+) tests? collected", proc.stdout)
    if not match:
        raise RuntimeError(
            "could not read a collected-test count from pytest:\n"
            f"stdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
        )
    return int(match.group(1))


def git(*args, capture=True):
    return subprocess.run(
        ["git", *args], cwd=ROOT, text=True,
        capture_output=capture, check=True,
    ).stdout


def fail(message):
    raise SystemExit(f"release: {message}")


def preflight(version):
    if git("rev-parse", "--abbrev-ref", "HEAD").strip() != "main":
        fail("not on main")

    dirty = {line[3:].strip() for line in git("status", "--porcelain").splitlines()}
    unexpected = sorted(dirty - ALLOWED_DIRTY)
    if unexpected:
        fail(f"uncommitted changes outside CHANGELOG.md: {', '.join(unexpected)}")

    current = plugin_version()
    if not is_newer(version, current):
        fail(f"{version} is not newer than the current {current}")

    newest = newest_changelog_version(read(CHANGELOG))
    if newest != version:
        fail(
            f"CHANGELOG.md's newest entry is {newest or 'missing'}, not {version}. "
            f"Write the '## [{version}]' entry first; its body becomes the Release notes."
        )

    if subprocess.run(["which", "gh"], capture_output=True).returncode != 0:
        fail("the gh CLI is required to publish the GitHub Release")


def supported_series(version):
    major, minor, _ = parse_version(version)
    return f"0.{minor}" if major == 0 else str(major)


def stated_security_series(text):
    matches = SECURITY_VERSION_RE.findall(text)
    if len(matches) != 1:
        raise ValueError(f"expected exactly one 'latest `N.x`' row in SECURITY.md, found {len(matches)}")
    return matches[0][1]


def set_security_series(text, version):
    stated_security_series(text)  # exactly one, or refuse
    series = supported_series(version)
    return SECURITY_VERSION_RE.sub(lambda m: m.group(1) + series + m.group(3), text, count=1)


def apply_edits(version, count):
    """Every file a release touches, written in one place.

    New contents are computed for all of them before any of them is written,
    so a transformer that refuses (a README whose Status section has moved,
    say) leaves the working tree untouched rather than half-bumped.
    """
    pending = {
        PLUGIN_JSON: set_json_version(read(PLUGIN_JSON), version),
        MARKETPLACE_JSON: set_json_version(read(MARKETPLACE_JSON), version),
        CODEX_PLUGIN_JSON: set_json_version(read(CODEX_PLUGIN_JSON), version),
        SECURITY_MD: set_security_series(read(SECURITY_MD), version),
    }
    for path, lang in READMES.items():
        text = set_status_version(read(path), version)
        pending[path] = set_test_counts(text, count, lang)

    for path, text in pending.items():
        path.write_text(text, encoding="utf-8")


def export_legacy_scripts(tag, dest):
    """Extract `tag`'s skill scripts into dest; return that scripts directory.
    A missing tag fails the release: the downgrade check must never be skipped
    by accident on the one run that is supposed to enforce it."""
    try:
        archive = subprocess.run(
            ["git", "archive", "--format=tar", tag, LEGACY_SCRIPTS],
            cwd=ROOT, capture_output=True, check=True,
        ).stdout
    except subprocess.CalledProcessError:
        fail(f"cannot export {LEGACY_SCRIPTS} from {tag}; the downgrade check needs that tag")
    with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
        tar.extractall(dest)
    return Path(dest) / LEGACY_SCRIPTS


def run_suite():
    with tempfile.TemporaryDirectory(prefix="audio-tldr-legacy-") as tmp:
        legacy = export_legacy_scripts(LEGACY_TAG, tmp)
        env = {**os.environ, "AUDIO_TLDR_LEGACY_SCRIPTS": str(legacy)}
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", str(ROOT / "tests"), "-q"],
            cwd=ROOT, text=True, env=env,
        )
    if proc.returncode != 0:
        fail("the suite is not green; nothing was committed, tagged or published")


def publish(version, notes):
    tag = f"v{version}"
    git("add", "-A")
    git("commit", "-m", f"chore(release): {tag}")
    git("tag", "-a", tag, "-m", tag)
    git("push", "origin", "main")
    git("push", "origin", tag)
    subprocess.run(
        ["gh", "release", "create", tag, "--title", tag, "--notes", notes],
        cwd=ROOT, check=True,
    )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("version", help="the new version, as a bare X.Y.Z")
    parser.add_argument(
        "--dry-run", action="store_true",
        help="run every check and report what would change, without writing anything",
    )
    args = parser.parse_args(argv)

    try:
        version = format_version(parse_version(args.version))
    except ValueError as exc:
        fail(str(exc))

    preflight(version)
    count = collected_test_count()
    notes = changelog_section(read(CHANGELOG), version)

    if args.dry_run:
        print(f"would release v{version} (currently {plugin_version()})")
        print(f"  manifests   -> {version}")
        print(f"  README docs -> v{version}, {count} tests")
        print(f"  tag         -> v{version}, pushed to origin/main")
        print(f"  release notes, first line: {notes.splitlines()[0] if notes else '(empty)'}")
        return 0

    apply_edits(version, count)
    run_suite()
    publish(version, notes)
    print(f"released v{version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
