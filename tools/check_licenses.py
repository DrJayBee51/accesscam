"""Verify the shipped runtime dependencies match what THIRD-PARTY-NOTICES.md
and packaging/licenses/ actually cover.

Three ways this drifts silently if nothing checks it: a dependency gets added
to pyproject.toml and nobody notices it needs a licence entry too; a
dependency's licence changes between versions (rare, but not unheard of - a
project can and occasionally does relicense); or a vendored licence file gets
deleted or renamed without anyone updating the doc that points at it. None of
those produce a Python import error, a failing test, or a lint warning - the
build keeps succeeding right up until someone actually reads the shipped
notices and finds them wrong.

Usage: python tools/check_licenses.py
Exits nonzero and explains what's out of sync if anything is.
"""

from __future__ import annotations

import re
import sys
import tomllib
from importlib.metadata import PackageNotFoundError, metadata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NOTICES = ROOT / "THIRD-PARTY-NOTICES.md"
LICENSE_DIR = ROOT / "packaging" / "licenses"

# The runtime dependencies that actually ship in a build, each mapped to the
# licence THIRD-PARTY-NOTICES.md documents for it and the vendored file(s)
# that have to exist to back that claim up. Distribution name (PyPI), not
# import name - opencv-python installs as "cv2", but metadata.metadata()
# wants the name pip knows it by.
#
# Kept here rather than derived automatically from pyproject.toml's bare
# dependency list, because the expected *licence* is exactly the fact a
# silent relicense would change without touching that list at all - deriving
# it from the same source being checked would make this a no-op.
EXPECTED = {
    "PySide6": {
        "licence_contains": "LGPL",
        "notice_mentions": ("PySide6", "LGPL-3.0"),
        "files": ["LGPL-3.0.txt"],
    },
    "shiboken6": {
        "licence_contains": "LGPL",
        "notice_mentions": ("shiboken6",),
        "files": ["LGPL-3.0.txt"],
    },
    "opencv-python": {
        "licence_contains": "Apache",
        "notice_mentions": ("OpenCV", "Apache-2.0"),
        "files": ["OpenCV-python-wrapper-LICENSE.txt", "OpenCV-LICENSE-3RD-PARTY.txt"],
    },
    "numpy": {
        "licence_contains": "BSD",
        "notice_mentions": ("NumPy", "BSD-3-Clause"),
        "files": ["NumPy-LICENSE.txt"],
    },
}


def declared_runtime_dependencies() -> set[str]:
    """The package names pyproject.toml actually ships, normalised.

    Only [project.dependencies] - the dev extras (pytest, ruff, PyInstaller)
    are build-time tools that never reach dist/AccessCam, and Inno Setup is not
    a Python dependency at all, so none of them belong in this check.
    """
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    names = set()
    for spec in data["project"]["dependencies"]:
        # Strip a version constraint like ">=6.7" down to the bare name.
        name = re.split(r"[<>=!~\[]", spec, maxsplit=1)[0].strip()
        names.add(name)
    return names


def _declared_licence(name: str) -> str:
    """The licence a package's own metadata claims, from whichever field it uses.

    Two generations of packaging metadata exist. The classic `License:` field
    is a free-text line (PySide6, opencv-python); the newer PEP 639
    `License-Expression:` is a structured SPDX expression that packages built
    with a recent setuptools - numpy among them - now emit instead, leaving
    `License:` blank. Checking only one silently treats every package using
    the other as unlicensed.
    """
    info = metadata(name)
    return info.get("License-Expression") or info.get("License") or ""


def main() -> int:
    problems: list[str] = []

    declared = declared_runtime_dependencies()
    # PySide6 pulls shiboken6 in as its own dependency rather than
    # AccessCam's; it still ships in every build and still needs covering.
    covered = declared | {"shiboken6"}

    unexpected = covered - EXPECTED.keys()
    if unexpected:
        problems.append(
            "Runtime dependencies with no licence entry in this script's EXPECTED "
            f"table: {', '.join(sorted(unexpected))}. Add one, and update "
            "THIRD-PARTY-NOTICES.md and packaging/licenses/ to match."
        )

    stale = EXPECTED.keys() - covered
    if stale:
        problems.append(
            f"EXPECTED lists {', '.join(sorted(stale))}, which pyproject.toml no "
            "longer depends on. Remove the stale entry (and its section in "
            "THIRD-PARTY-NOTICES.md) rather than leave it claiming something is "
            "bundled that is not."
        )

    notices_text = NOTICES.read_text(encoding="utf-8") if NOTICES.exists() else ""
    if not notices_text:
        problems.append(f"{NOTICES.relative_to(ROOT)} is missing or empty.")

    for name, expectation in EXPECTED.items():
        if name not in covered:
            continue  # already reported above as stale

        try:
            declared_licence = _declared_licence(name)
        except PackageNotFoundError:
            problems.append(
                f"{name} is expected but not installed - run `pip install -e .[dev]` "
                "before checking, or the licence actually shipped cannot be confirmed."
            )
            declared_licence = None

        if declared_licence is not None and expectation["licence_contains"] not in declared_licence:
            problems.append(
                f"{name}'s installed metadata says {declared_licence!r}, which does not "
                f"contain {expectation['licence_contains']!r}. Either the package "
                "relicensed, or EXPECTED is wrong - check before assuming either."
            )

        for phrase in expectation["notice_mentions"]:
            if notices_text and phrase not in notices_text:
                problems.append(
                    f"THIRD-PARTY-NOTICES.md no longer mentions {phrase!r}, expected for {name}."
                )

        for filename in expectation["files"]:
            path = LICENSE_DIR / filename
            if not path.is_file() or path.stat().st_size == 0:
                problems.append(
                    f"{path.relative_to(ROOT)} is missing or empty, but "
                    f"THIRD-PARTY-NOTICES.md says it ships for {name}."
                )

    if problems:
        print("Third-party licence coverage is out of sync:\n")
        for problem in problems:
            print(f"  - {problem}")
        return 1

    print(f"OK: {len(covered)} runtime dependencies match THIRD-PARTY-NOTICES.md.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
