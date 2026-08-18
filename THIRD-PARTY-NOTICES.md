# Third-party notices

AccessCam's own code is MIT-licensed - see `LICENSE`. This file covers what a
built AccessCam distributes *alongside* that code: the runtime libraries a
PyInstaller build bundles into `dist/AccessCam/`, without which the
application cannot run. Development-only tooling - pytest, ruff, PyInstaller
itself, the Inno Setup compiler - never ships in that folder and is not
covered here, since it is a build-time dependency of the *maintainer*, not a
distribution obligation to the *user*.

The verbatim license text for everything below is vendored in
`packaging/licenses/` and ships in every installed copy of AccessCam under a
`licenses\` folder beside `AccessCam.exe`. `tools/check_licenses.py` verifies
this list stays in sync with what `pyproject.toml` actually declares -
run it (or let CI run it) after changing a dependency.

## Qt / PySide6 / shiboken6 - LGPL-3.0-only

**What it is.** PySide6 is the official Python binding for Qt, built by the Qt
Company; shiboken6 is the binding generator it depends on. Both are dual/
triple-licensed (LGPL-3.0-only, GPL-2.0-only, or a commercial Qt licence, at
the licensor's offering) - AccessCam relies on the **LGPL-3.0-only** option,
which is the one that permits combining Qt with MIT-licensed code without
requiring AccessCam itself to become GPL.

**How AccessCam uses it, and why that satisfies the license.** LGPLv3 §4
allows conveying a "Combined Work" - an application linked against the
Library - under terms of the developer's choosing, provided (among other
things) that the Library can be relinked: either by shipping source the user
can rebuild and relink (§4(d)(0)), or by using "a suitable shared library
mechanism" that lets a user replace the Library with a modified or different
compatible version and have the application keep working (§4(d)(1)).

AccessCam's build is a **one-folder** PyInstaller distribution specifically
because of this (see `docs/PROJECT_PLAN.md`, M4.3): `Qt6Core.dll`,
`Qt6Widgets.dll`, `shiboken6.dll` and the rest of Qt sit as ordinary,
unmodified DLL files beside `AccessCam.exe`, loaded at runtime through
Windows' normal dynamic-linking mechanism rather than compiled into the
executable. Any user can replace those DLLs with a different build of the
same Qt version and AccessCam will load and run against it unchanged - which
is exactly the "suitable shared library mechanism" §4(d)(1) describes.
(A `--onefile` build, which unpacks everything into a private temp directory
at every launch, would make this materially harder to argue - one more reason
that shape was rejected for reasons entirely unrelated to licensing.)

Unmodified Qt source is publicly available from the Qt Project regardless -
https://code.qt.io/cgit/qt/qt5.git and https://download.qt.io - so there is no
"minimal corresponding source" for AccessCam to additionally provide: nothing
about Qt itself is modified here.

**What ships:** `packaging/licenses/LGPL-3.0.txt`, fetched verbatim from
https://www.gnu.org/licenses/lgpl-3.0.txt (LGPLv3 itself incorporates GPLv3 by
reference in its own text, so no separate GPL copy is bundled).

## OpenCV / opencv-python - Apache-2.0 (core) + MIT (Python wrapper)

**What it is.** `opencv-python` is a thin MIT-licensed Python wrapper (built
by Olli-Pekka Heinisuo) around a compiled OpenCV binary, which is itself
Apache-2.0 licensed, plus a substantial set of third-party components OpenCV
bundles (libjpeg, libpng, zlib, protobuf, and others), each under its own
license.

**What ships:**
`packaging/licenses/OpenCV-python-wrapper-LICENSE.txt` (the wrapper's own MIT
text) and `packaging/licenses/OpenCV-LICENSE-3RD-PARTY.txt` (OpenCV's own
combined notice, vendored verbatim from the installed wheel rather than
hand-curated - it already opens with "OpenCV library is redistributed within
opencv-python package. This license applies to OpenCV binary in the directory
cv2/", followed by the full Apache License 2.0 and then every third-party
license OpenCV itself carries). Reproducing OpenCV's own file whole, rather
than re-deriving it, is what avoids silently dropping a component OpenCV adds
in a future version.

## NumPy - BSD-3-Clause (plus bundled components under their own licenses)

**What it is.** NumPy's own code is 3-clause BSD. Like OpenCV, its wheel
bundles compiled numerical routines (OpenBLAS, LAPACK, and others) under
their own licenses, combined into one file upstream.

**What ships:** `packaging/licenses/NumPy-LICENSE.txt`, vendored verbatim
from the installed wheel for the same reason as OpenCV's. PyInstaller's own
NumPy hook additionally bundles NumPy's complete internal
`licenses/` tree (per-component texts for pocketfft, pcg64, and the rest)
directly into every build under `_internal\numpy-<version>.dist-info\
licenses\` - already present without any action here, and left there as the
authoritative copy rather than duplicated into `packaging/licenses/`.

## Versions covered

Recorded at the versions installed when this file was last checked
(2026-08-18); `tools/check_licenses.py` reports the versions actually
installed in the current environment, which is the number that matters at
build time.

| Package | Version | License |
|---|---|---|
| PySide6 | 6.11.1 | LGPL-3.0-only |
| shiboken6 | 6.11.1 | LGPL-3.0-only |
| opencv-python | 5.0.0.93 | Apache-2.0 (core) + MIT (wrapper) |
| numpy | 2.5.1 | BSD-3-Clause |
