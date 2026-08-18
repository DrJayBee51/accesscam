"""Write the application icon from the same glyph the tray draws.

    python tools/make_icon.py assets/accesscam.ico

One drawing, three uses: the tray, this icon, and the marker the preview
overlays on the tracked dot. Generating rather than shipping a hand-drawn file
is what keeps them from drifting apart.

The green is the driving colour rather than the parked red, since an icon sits
still and a red one reads as a warning.
"""

from __future__ import annotations

import struct
import sys
from pathlib import Path

from PySide6.QtCore import QBuffer
from PySide6.QtWidgets import QApplication

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from accesscam.ui.tray import ACTIVE, marker_pixmap  # noqa: E402

# Each size is *drawn*, not downsampled. A 2px ring survives neither a
# resampler nor Windows picking the 256px image for a 16px slot in the taskbar.
SIZES = (16, 24, 32, 48, 64, 128, 256)

DEFAULT_OUT = Path("assets/accesscam.ico")


def png_bytes(size: int) -> bytes:
    """One rendering of the glyph, PNG-compressed.

    Qt's own ICO writer stores a single image, so the container is assembled
    here instead. PNG payloads inside an ICO are understood by everything from
    Vista on, and turn a 270KB file of raw BGRA into a few kilobytes.
    """
    # QBuffer with no argument owns its storage. Handing it a QByteArray built
    # inline instead crashes the interpreter: the temporary is collected while
    # Qt still holds a pointer into it.
    buffer = QBuffer()
    buffer.open(QBuffer.OpenModeFlag.WriteOnly)
    marker_pixmap(ACTIVE, size).save(buffer, "PNG")
    buffer.close()
    return bytes(buffer.data())


def build_ico(sizes) -> bytes:
    images = [png_bytes(size) for size in sizes]

    header = struct.pack("<HHH", 0, 1, len(images))  # reserved, type 1 = icon
    offset = len(header) + 16 * len(images)

    directory = b""
    for size, data in zip(sizes, images, strict=True):
        directory += struct.pack(
            "<BBBBHHII",
            size if size < 256 else 0,  # 0 means 256; the field is one byte
            size if size < 256 else 0,
            0,  # palette size, 0 for truecolour
            0,  # reserved
            1,  # colour planes
            32,  # bits per pixel
            len(data),
            offset,
        )
        offset += len(data)

    return header + directory + b"".join(images)


def main() -> int:
    argv = [a for a in sys.argv[1:] if a != "--force"]
    force = "--force" in sys.argv[1:]
    out = Path(argv[0]) if argv else DEFAULT_OUT

    # This generates the *fallback* glyph. Once real artwork exists at the
    # target path - which it does, hand-drawn - regenerating over it destroys
    # work that cannot be recovered from source, since the source is a GIMP
    # file this script knows nothing about. Refusing by default costs one flag
    # on the rare occasion the fallback genuinely needs rebuilding.
    if out.exists() and not force:
        print(f"{out} already exists - refusing to overwrite it.", file=sys.stderr)
        print(
            "This script regenerates the drawn fallback glyph. If that file is "
            "hand-drawn artwork, regenerating would discard it.",
            file=sys.stderr,
        )
        print("Pass --force if you really mean to replace it.", file=sys.stderr)
        return 1

    out.parent.mkdir(parents=True, exist_ok=True)

    QApplication([])
    out.write_bytes(build_ico(SIZES))

    print(f"wrote {out} ({', '.join(str(s) for s in SIZES)}px, {out.stat().st_size:,} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
