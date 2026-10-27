#!/usr/bin/env python3
"""Validate and build deterministic ZIPs for the Agensi listings."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import sys
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from PIL import Image
import yaml


ROOT = Path(__file__).resolve().parents[1]
LISTING_ROOT = ROOT / "marketplace" / "listings"
MAX_ZIP_BYTES = 50 * 1024 * 1024
MAX_FILES = 1000
MAX_TEXT_FILES = 200
MAX_TEXT_CHARS = 6_000_000
MAX_SCRIPT_BYTES = 20 * 1024
BLOCKED_SUFFIXES = {
    ".exe", ".dll", ".so", ".dylib", ".bin", ".app", ".dmg", ".msi",
    ".deb", ".rpm", ".wasm", ".class", ".jar", ".war",
}
IGNORED_PARTS = {"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"}
SECRET_PATTERNS = (
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"\bsk-(?:proj-|live-)?[A-Za-z0-9_-]{20,}"),
)
INJECTION_PATTERNS = (
    re.compile(r"ignore\s+(?:all\s+)?previous\s+instructions", re.I),
    re.compile(r"do\s+not\s+tell\s+the\s+user", re.I),
    re.compile(r"\bsecretly\b", re.I),
)


def relative(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def read_json_text(path: Path) -> tuple[str, str]:
    data = path.read_bytes()
    for encoding in ("utf-8-sig", "utf-8"):
        try:
            return data.decode(encoding), encoding
        except UnicodeDecodeError:
            pass
    raise ValueError(f"{relative(path)}: expected a UTF-8 text file")


def load_listing(path: Path) -> dict:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{relative(path)}: listing must be a mapping")
    required = {
        "schema_version", "slug", "skill_dir", "name", "summary",
        "description_file", "demo_file", "logo", "categories", "tags",
        "use_cases", "compatibility", "requires", "permissions",
        "known_limitations", "license",
    }
    missing = sorted(required - data.keys())
    if missing:
        raise ValueError(f"{relative(path)}: missing fields {missing}")
    if data["schema_version"] != 1:
        raise ValueError(f"{relative(path)}: unsupported schema version")
    return data


def check_listing(data: dict, source: Path) -> None:
    name = data["name"]
    summary = data["summary"]
    if not isinstance(name, str) or not 1 <= len(name) <= 60:
        raise ValueError(f"{relative(source)}: name must contain 1-60 characters")
    if not isinstance(summary, str) or not 1 <= len(summary) <= 300:
        raise ValueError(f"{relative(source)}: summary must contain 1-300 characters")
    categories = data["categories"]
    if not isinstance(categories, list) or not 1 <= len(categories) <= 3:
        raise ValueError(f"{relative(source)}: use one to three categories")
    for field in ("tags", "use_cases", "requires", "known_limitations"):
        if not isinstance(data[field], list) or not data[field]:
            raise ValueError(f"{relative(source)}: {field} must be a nonempty list")
    if not isinstance(data["permissions"], dict) or not data["permissions"]:
        raise ValueError(f"{relative(source)}: permissions must be a mapping")

    demo_path = ROOT / data["demo_file"]
    description_path = ROOT / data["description_file"]
    demo = demo_path.read_text(encoding="utf-8").strip()
    description = description_path.read_text(encoding="utf-8").strip()
    if len(demo) < 700:
        raise ValueError(
            f"{relative(demo_path)}: demo must contain at least 700 characters"
        )
    if len(description) < 200:
        raise ValueError(f"{relative(description_path)}: description is too short")

    logo = ROOT / data["logo"]
    with Image.open(logo) as image:
        if image.size != (512, 512):
            raise ValueError(f"{relative(logo)}: logo must be exactly 512 x 512")
        if image.format not in {"PNG", "WEBP"}:
            raise ValueError(f"{relative(logo)}: logo must be PNG or WEBP")
    if logo.stat().st_size > 5 * 1024 * 1024:
        raise ValueError(f"{relative(logo)}: logo exceeds 5 MB")

    screenshots = data.get("screenshots", [])
    if not isinstance(screenshots, list) or len(screenshots) > 6:
        raise ValueError(f"{relative(source)}: use no more than six screenshots")
    for screenshot_name in screenshots:
        screenshot = ROOT / screenshot_name
        if screenshot.stat().st_size > 10 * 1024 * 1024:
            raise ValueError(f"{relative(screenshot)}: screenshot exceeds 10 MB")
        with Image.open(screenshot):
            pass


def is_test_file(path: Path) -> bool:
    return path.name.startswith("test_") and path.suffix == ".py"


def package_files(data: dict) -> list[Path]:
    skill_dir = ROOT / data["skill_dir"]
    if not skill_dir.is_dir():
        raise ValueError(f"{relative(skill_dir)}: missing skill directory")
    files = []
    for path in sorted(skill_dir.rglob("*")):
        if not path.is_file() or is_test_file(path):
            continue
        if any(part in IGNORED_PARTS for part in path.parts):
            continue
        if path.suffix.lower() in BLOCKED_SUFFIXES:
            raise ValueError(f"{relative(path)}: executable or package type is blocked")
        files.append(path)
    return files


def check_skill_package(data: dict, files: list[Path]) -> dict:
    skill_markdown = [path for path in files if path.name == "SKILL.md"]
    if len(skill_markdown) != 1:
        raise ValueError(
            f"{data['slug']}: package must contain exactly one SKILL.md"
        )
    frontmatter = skill_markdown[0].read_text(encoding="utf-8")
    if not frontmatter.startswith("---\n") or "\n---\n" not in frontmatter[4:]:
        raise ValueError(f"{relative(skill_markdown[0])}: invalid frontmatter")

    text_files = 0
    text_characters = 0
    entries = []
    for path in files:
        package_path = PurePosixPath(
            path.relative_to(ROOT / data["skill_dir"]).as_posix()
        )
        if package_path.is_absolute() or ".." in package_path.parts:
            raise ValueError(f"{relative(path)}: unsafe package path")
        content = path.read_bytes()
        text = None
        try:
            text = content.decode("utf-8-sig")
        except UnicodeDecodeError:
            if path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp", ".pdf"}:
                raise ValueError(f"{relative(path)}: unknown binary file type")
        if text is not None:
            text_files += 1
            text_characters += len(text)
            for pattern in SECRET_PATTERNS:
                if pattern.search(text):
                    raise ValueError(f"{relative(path)}: possible committed secret")
            for pattern in INJECTION_PATTERNS:
                if pattern.search(text):
                    raise ValueError(f"{relative(path)}: prompt-injection phrase found")
        if path.suffix == ".py" and path.stat().st_size > MAX_SCRIPT_BYTES:
            raise ValueError(
                f"{relative(path)}: production script exceeds the 20 KB guideline"
            )
        entries.append(
            {
                "path": str(package_path),
                "bytes": len(content),
                "sha256": hashlib.sha256(content).hexdigest(),
            }
        )
    if len(files) + 1 > MAX_FILES:
        raise ValueError(f"{data['slug']}: package exceeds {MAX_FILES} files")
    if text_files > MAX_TEXT_FILES:
        raise ValueError(f"{data['slug']}: package exceeds {MAX_TEXT_FILES} text files")
    if text_characters > MAX_TEXT_CHARS:
        raise ValueError(f"{data['slug']}: package exceeds {MAX_TEXT_CHARS} characters")
    return {
        "slug": data["slug"],
        "submission_status": data.get("submission_status", "not_declared"),
        "skill": relative(skill_markdown[0]),
        "source_files": len(files),
        "text_files": text_files,
        "text_characters": text_characters,
        "largest_production_script_bytes": max(
            (path.stat().st_size for path in files if path.suffix == ".py"),
            default=0,
        ),
        "files": entries,
    }


def zip_info(name: str) -> ZipInfo:
    info = ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = ZIP_DEFLATED
    info.external_attr = (0o100644 & 0xFFFF) << 16
    return info


def build_zip(data: dict, files: list[Path], output_dir: Path) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    zip_path = output_dir / f"{data['slug']}-agensi.zip"
    with ZipFile(zip_path, "w", compression=ZIP_DEFLATED, compresslevel=9) as archive:
        skill_dir = ROOT / data["skill_dir"]
        for path in files:
            archive.writestr(
                zip_info(
                    f"{data['slug']}/"
                    + path.relative_to(skill_dir).as_posix()
                ),
                path.read_bytes(),
            )
        archive.writestr(
            zip_info(f"{data['slug']}/LICENSE"),
            (ROOT / "LICENSE").read_bytes(),
        )
    size = zip_path.stat().st_size
    if size > MAX_ZIP_BYTES:
        raise ValueError(f"{zip_path.name}: ZIP exceeds 50 MB")
    digest = hashlib.sha256(zip_path.read_bytes()).hexdigest()
    (output_dir / f"{zip_path.name}.sha256").write_text(
        f"{digest}  {zip_path.name}\n", encoding="ascii"
    )
    return {
        "slug": data["slug"],
        "path": zip_path.name,
        "bytes": size,
        "sha256": digest,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--out", type=Path, default=ROOT / "dist" / "agensi")
    args = parser.parse_args()

    listing_paths = sorted(LISTING_ROOT.glob("*.yaml"))
    if not listing_paths:
        raise ValueError("marketplace/listings: no listings found")
    summaries = []
    builds = []
    seen = set()
    for listing_path in listing_paths:
        data = load_listing(listing_path)
        if data["slug"] in seen:
            raise ValueError(f"duplicate listing slug {data['slug']!r}")
        seen.add(data["slug"])
        check_listing(data, listing_path)
        files = package_files(data)
        summary = check_skill_package(data, files)
        summary["listing"] = relative(listing_path)
        summaries.append(summary)
        if not args.check:
            builds.append(build_zip(data, files, args.out.resolve()))

    payload = {"status": "ok", "listings": summaries, "builds": builds}
    if not args.check:
        (args.out.resolve() / "manifest.json").write_text(
            json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
        )
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, UnicodeError, ValueError, yaml.YAMLError) as error:
        print(f"Agensi release check failed: {error}", file=sys.stderr)
        raise SystemExit(1)
