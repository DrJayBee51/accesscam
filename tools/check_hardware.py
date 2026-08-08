"""Verify every part folder in hardware/ contains SolidWorks, STL, and STEP files.

Usage: python tools/check_hardware.py
Exits nonzero and lists what's missing if any part folder is incomplete.
"""

import sys
from pathlib import Path

HARDWARE_DIR = Path(__file__).resolve().parent.parent / "hardware"

REQUIRED = {
    "SolidWorks source (.sldprt/.sldasm)": {".sldprt", ".sldasm"},
    "STL export (.stl)": {".stl"},
    "STEP export (.step/.stp)": {".step", ".stp"},
}


def main() -> int:
    part_dirs = sorted(
        d for d in HARDWARE_DIR.iterdir() if d.is_dir() and not d.name.startswith(".")
    )
    if not part_dirs:
        print("No part folders in hardware/ yet - nothing to check.")
        return 0

    failures = []
    for part in part_dirs:
        extensions = {f.suffix.lower() for f in part.rglob("*") if f.is_file()}
        missing = [label for label, exts in REQUIRED.items() if not extensions & exts]
        if missing:
            failures.append((part.name, missing))

    if failures:
        print("Incomplete part folders in hardware/:\n")
        for name, missing in failures:
            print(f"  {name}/ is missing:")
            for label in missing:
                print(f"    - {label}")
        print("\nEach part folder must contain a SolidWorks source, an STL, and a STEP file.")
        return 1

    print(f"OK: {len(part_dirs)} part folder(s) complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
