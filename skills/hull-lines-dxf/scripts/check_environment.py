#!/usr/bin/env python3
"""Check the local runtime needed by hull-lines-dxf without changing it."""

from __future__ import annotations

import importlib.metadata
import json
import platform
import sys


REQUIRED = {
    "ezdxf": "1.4.4",
    "numpy": "2.2",
    "scipy": "1.15",
    "matplotlib": "3.10",
    "fonttools": "4.55",
    "Pillow": "11",
}


def version_tuple(value: str) -> tuple[int, ...]:
    parts = []
    for item in value.split("."):
        digits = "".join(character for character in item if character.isdigit())
        if not digits:
            break
        parts.append(int(digits))
    return tuple(parts)


def main() -> int:
    checks = {}
    missing = []
    outdated = []
    for package, minimum in REQUIRED.items():
        try:
            found = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            checks[package] = {"required": minimum, "found": None, "status": "missing"}
            missing.append(package)
            continue
        ok = version_tuple(found) >= version_tuple(minimum)
        checks[package] = {
            "required": minimum,
            "found": found,
            "status": "ok" if ok else "outdated",
        }
        if not ok:
            outdated.append(package)

    python_ok = sys.version_info >= (3, 10)
    report = {
        "status": "ok" if python_ok and not missing and not outdated else "blocked",
        "python": {
            "version": platform.python_version(),
            "required": ">=3.10",
            "status": "ok" if python_ok else "outdated",
        },
        "packages": checks,
    }
    print(json.dumps(report, indent=2, ensure_ascii=False))
    if report["status"] != "ok":
        print(
            "Install or upgrade the documented runtime from the skill's "
            "scripts/requirements.txt, then rerun this check.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
