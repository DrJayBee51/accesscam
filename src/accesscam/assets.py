"""Finding the files that ship beside the code.

Two places to look, because there are two ways AccessCam runs. From a source
checkout the assets sit in `assets/` next to `src/`. Frozen by PyInstaller they
are unpacked into the bundle, and `sys._MEIPASS` is where.

Everything here returns None rather than raising when a file is absent. Art is
decoration: a missing icon must never be the reason somebody's pointer does not
work.
"""

from __future__ import annotations

import sys
from pathlib import Path

ASSET_DIR_NAME = "assets"


def asset_root() -> Path:
    """The directory shipped assets live in, whether frozen or not."""
    bundle = getattr(sys, "_MEIPASS", None)
    if bundle is not None:
        return Path(bundle) / ASSET_DIR_NAME

    # src/accesscam/assets.py -> src/accesscam -> src -> the repository root.
    return Path(__file__).resolve().parents[2] / ASSET_DIR_NAME


def asset(name: str) -> Path | None:
    """One shipped file, or None if it is not there."""
    candidate = asset_root() / name
    return candidate if candidate.is_file() else None
