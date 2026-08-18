# PyInstaller build: one folder, no console, versioned by the package.
#
#     pyinstaller packaging/accesscam.spec --noconfirm
#
# One folder rather than one file. A --onefile build unpacks itself to a temp
# directory on every launch, which costs seconds at logon - the exact moment
# AccessCam is racing the camera and the shell already - and leaves antivirus
# software watching an executable materialise from nowhere at every boot.
#
# The manifest deliberately does NOT request administrator rights. AccessCam
# wants them (see docs/RUNNING.md on UIPI), but requiring them would make the
# program unusable for anyone who is not an administrator of their own machine
# - a real case in the schools and centres this is meant for. It runs as
# whoever launched it, says so in the window when that is not enough, and
# offers the scheduled task as the way up.

import sys
from pathlib import Path

sys.path.insert(0, str(Path(SPECPATH).parent / "src"))
from accesscam import __version__  # noqa: E402

ROOT = Path(SPECPATH).parent

a = Analysis(
    [str(ROOT / "src" / "accesscam" / "__main__.py")],
    pathex=[str(ROOT / "src")],
    binaries=[],
    datas=[],
    hiddenimports=["accesscam.mouse.windows", "accesscam.hotkeys.windows"],
    hookspath=[],
    runtime_hooks=[],
    # Qt ships far more than a settings window needs, and every megabyte is a
    # megabyte someone downloads over a school's connection.
    excludes=[
        "tkinter",
        "PySide6.QtWebEngineCore",
        "PySide6.QtWebEngineWidgets",
        "PySide6.QtQuick",
        "PySide6.QtQml",
        "PySide6.Qt3DCore",
        "PySide6.QtMultimedia",
        "PySide6.QtCharts",
        "PySide6.QtDataVisualization",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="AccessCam",
    debug=False,
    strip=False,
    upx=False,
    # No console. python.exe would put a black box behind the window at every
    # launch, for a program that has a GUI and prints to a log file instead.
    console=False,
    icon=str(ROOT / "assets" / "accesscam.ico"),
    version_info={"version": __version__},
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="AccessCam",
)
