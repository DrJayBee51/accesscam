"""Verify every part folder in hardware/ carries its required exports.

Part folders (a .sldprt source) must also contain an STL and a STEP file, so a
contributor without SolidWorks can both print and modify the design. Assembly
folders (a .sldasm source) only need the assembly itself - an assembly is a
container of parts, not something you print as a single mesh.

Usage: python tools/check_hardware.py
Exits nonzero and lists what's missing if anything is incomplete.
"""

import sys
from pathlib import Path

HARDWARE_DIR = Path(__file__).resolve().parent.parent / "hardware"

PART_SOURCE = {".sldprt"}
ASSEMBLY_SOURCE = {".sldasm"}

PART_EXPORTS = {
    "STL export (.stl)": {".stl"},
    "STEP export (.step/.stp)": {".step", ".stp"},
}


def missing_from(extensions: set[str]) -> list[str]:
    """Return the labels of required files absent from one part folder."""
    if extensions & ASSEMBLY_SOURCE:
        return []
    if not extensions & PART_SOURCE:
        return ["SolidWorks source (.sldprt/.sldasm)"] + [
            label for label, exts in PART_EXPORTS.items() if not extensions & exts
        ]
    return [label for label, exts in PART_EXPORTS.items() if not extensions & exts]


def main() -> int:
    part_dirs = sorted(
        d for d in HARDWARE_DIR.iterdir() if d.is_dir() and not d.name.startswith(".")
    )
    if not part_dirs:
        print("No part folders in hardware/ yet - nothing to check.")
        return 0

    failures = []
    empty = []
    for part in part_dirs:
        extensions = {f.suffix.lower() for f in part.rglob("*") if f.is_file()}
        if not extensions:
            # Git cannot track empty directories, so these never reach CI.
            # Treat them as work in progress rather than an error.
            empty.append(part.name)
            continue
        missing = missing_from(extensions)
        if missing:
            failures.append((part.name, missing))

    for name in empty:
        print(f"Note: {name}/ is empty (work in progress, not tracked by git).")

    if failures:
        print("Incomplete part folders in hardware/:\n")
        for name, missing in failures:
            print(f"  {name}/ is missing:")
            for label in missing:
                print(f"    - {label}")
        print("\nEach part folder needs a SolidWorks source; parts also need an STL and STEP.")
        return 1

    complete = len(part_dirs) - len(empty)
    print(f"OK: {complete} part folder(s) complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
