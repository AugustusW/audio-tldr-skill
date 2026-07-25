"""Offline tests for built-in digest templates (no network, no models)."""
import re
from pathlib import Path

import pytest

TEMPLATES_DIR = Path(__file__).parent.parent / "skills" / "audio-tldr" / "templates"
BUILTIN = ["meeting-minutes", "key-summary", "analysis-report"]


def _parse_frontmatter(text: str) -> dict:
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", text, re.DOTALL)
    assert m, "template must start with YAML frontmatter"
    fm = {}
    for line in m.group(1).splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            fm[k.strip()] = v.strip()
    return {"fields": fm, "body": m.group(2)}


@pytest.mark.parametrize("slug", BUILTIN)
def test_builtin_template_exists(slug):
    assert (TEMPLATES_DIR / f"{slug}.md").is_file()


@pytest.mark.parametrize("slug", BUILTIN)
def test_builtin_template_frontmatter_complete(slug):
    parsed = _parse_frontmatter((TEMPLATES_DIR / f"{slug}.md").read_text(encoding="utf-8"))
    assert parsed["fields"].get("name") == slug
    assert parsed["fields"].get("description"), "description must be non-empty"


@pytest.mark.parametrize("slug", BUILTIN)
def test_builtin_template_body_has_sections(slug):
    parsed = _parse_frontmatter((TEMPLATES_DIR / f"{slug}.md").read_text(encoding="utf-8"))
    assert parsed["body"].strip(), "template body must be non-empty"
    assert "## " in parsed["body"], "template body must define at least one section"
