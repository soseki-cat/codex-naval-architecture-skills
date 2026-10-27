#!/usr/bin/env python3
"""Validate the repository's skill entrypoints and local Markdown links."""

from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
SKILLS_ROOT = ROOT / "skills"
FRONTMATTER = re.compile(r"\A---\r?\n(.*?)\r?\n---\r?\n", re.DOTALL)
MARKDOWN_LINK = re.compile(r"!?\[[^\]]*]\(([^)]+)\)")
EXTERNAL_PREFIXES = ("http://", "https://", "mailto:", "#", "/")


def display(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def load_frontmatter(path: Path) -> dict:
    text = read_text(path)
    match = FRONTMATTER.match(text)
    if not match:
        raise ValueError(f"{display(path)}: missing YAML frontmatter")
    data = yaml.safe_load(match.group(1))
    if not isinstance(data, dict):
        raise ValueError(f"{display(path)}: frontmatter must be a mapping")
    return data


def check_skill(skill_dir: Path) -> None:
    entrypoint = skill_dir / "SKILL.md"
    if not entrypoint.is_file():
        raise ValueError(f"{display(skill_dir)}: missing SKILL.md")

    data = load_frontmatter(entrypoint)
    missing = {"name", "description"} - data.keys()
    if missing:
        raise ValueError(f"{display(entrypoint)}: missing fields {sorted(missing)}")
    if data["name"] != skill_dir.name:
        raise ValueError(
            f"{display(entrypoint)}: name {data['name']!r} does not match folder {skill_dir.name!r}"
        )
    if not isinstance(data["description"], str) or len(data["description"].strip()) < 20:
        raise ValueError(f"{display(entrypoint)}: description is too short")

    agent_metadata = skill_dir / "agents" / "openai.yaml"
    if agent_metadata.exists():
        metadata = yaml.safe_load(read_text(agent_metadata))
        if not isinstance(metadata, dict):
            raise ValueError(f"{display(agent_metadata)}: expected a YAML mapping")


def check_markdown_links(path: Path) -> None:
    text = read_text(path)
    for raw_target in MARKDOWN_LINK.findall(text):
        target = raw_target.strip()
        if target.startswith(EXTERNAL_PREFIXES):
            continue
        target = target.split(maxsplit=1)[0].split("#", maxsplit=1)[0]
        if not target:
            continue
        destination = (path.parent / target).resolve()
        if not destination.exists():
            raise ValueError(
                f"{display(path)}: broken local link {raw_target!r} -> {display(destination)}"
            )


def main() -> int:
    skill_dirs = sorted(path for path in SKILLS_ROOT.iterdir() if path.is_dir())
    if not skill_dirs:
        raise ValueError("skills/: no skill directories found")

    for skill_dir in skill_dirs:
        check_skill(skill_dir)

    for markdown in sorted(ROOT.rglob("*.md")):
        if ".git" not in markdown.parts:
            check_markdown_links(markdown)

    print(f"Validated {len(skill_dirs)} skills and local Markdown links.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, UnicodeError, ValueError, yaml.YAMLError) as exc:
        print(f"Validation failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
