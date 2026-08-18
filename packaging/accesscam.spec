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


def _windows_version_tuple(version: str) -> tuple[int, int, int, int]:
    """Pad a PEP 440-ish version out to the four integers Windows wants.

    A Windows FILEVERSION resource is always four numbers; "0.1.0" has three,
    so the release build number is padded with a trailing zero.
    """
    parts = [int(p) for p in version.split(".")[:4]]
    return tuple((parts + [0, 0, 0, 0])[:4])


def _version_resource():
    """The Windows version resource, so the exe answers to more than a filename.

    Without this, Explorer's Properties > Details tab is blank and the
    installer has nothing reliable to read the version from except re-running
    Python. PyInstaller's `version=` wants this structure specifically - a
    plain dict is accepted silently and produces an exe with no version
    resource at all, which is what the first build actually shipped.
    """
    from PyInstaller.utils.win32.versioninfo import (
        FixedFileInfo,
        StringFileInfo,
        StringStruct,
        StringTable,
        VarFileInfo,
        VarStruct,
        VSVersionInfo,
    )

    numbers = _windows_version_tuple(__version__)
    return VSVersionInfo(
        ffi=FixedFileInfo(filevers=numbers, prodvers=numbers),
        kids=[
            StringFileInfo(
                [
                    StringTable(
                        "040904B0",
                        [
                            StringStruct("CompanyName", "AccessCam"),
                            StringStruct("FileDescription", "AccessCam"),
                            StringStruct("FileVersion", __version__),
                            StringStruct("InternalName", "AccessCam"),
                            StringStruct("OriginalFilename", "AccessCam.exe"),
                            StringStruct("ProductName", "AccessCam"),
                            StringStruct("ProductVersion", __version__),
                            StringStruct(
                                "LegalCopyright", "MIT licensed - see LICENSE"
                            ),
                        ],
                    )
                ]
            ),
            VarFileInfo([VarStruct("Translation", [1033, 1200])]),
        ],
    )

a = Analysis(
    [str(ROOT / "src" / "accesscam" / "__main__.py")],
    pathex=[str(ROOT / "src")],
    binaries=[],
    # Shipped artwork, looked up at runtime through accesscam.assets. Named
    # rather than globbed so a stray file in assets/ cannot swell the bundle.
    datas=[
        (str(ROOT / "assets" / name), "assets")
        for name in ("accesscam.ico", "tray-active.png", "tray-paused.png")
        if (ROOT / "assets" / name).is_file()
    ],
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
    version=_version_resource(),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="AccessCam",
)
