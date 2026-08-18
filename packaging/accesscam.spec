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

import os
import sys
from pathlib import Path

ROOT = Path(SPECPATH).parent
sys.path.insert(0, str(ROOT / "src"))
from accesscam import __version__  # noqa: E402
from accesscam.ui.tray import APP_ICON  # noqa: E402


# UIAccess: the mechanism that lets an unelevated program drive higher-integrity
# windows - on-screen keyboards, UAC-elevated applications - which is exactly
# what AccessCam needs and currently solves by running elevated instead. It is
# how the SmartNav does it (its external smartnav.exe.manifest carries
# level="asInvoker" uiAccess="true"), and it is strictly better: no admin
# rights, no UAC prompt, and it works for a user who is not an administrator of
# their own machine.
#
# Opt-in, and it has to be, because Windows grants UIAccess only when the
# executable is BOTH Authenticode-signed by a trusted publisher AND installed
# under Program Files (or System32). Fail either and the process does not
# launch degraded - it does not launch at all: "A referral was returned from
# the server", verified 2026-08-18 against an unsigned build in dist/. Making
# this unconditional would produce a build that cannot start until the day a
# certificate is bought.
#
#     set ACCESSCAM_UIACCESS=1     (release builds, once signing exists)
#
# See docs/PROJECT_PLAN.md M4.8 for the certificate question this waits on.
UIACCESS = os.environ.get("ACCESSCAM_UIACCESS") == "1"


def _art_filenames() -> list[str]:
    from accesscam.ui.tray import TRAY_ART

    return list(TRAY_ART.values())


def _licence_filenames() -> list[str]:
    return sorted(p.name for p in (ROOT / "packaging" / "licenses").glob("*.txt"))


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
    # Shipped artwork, looked up at runtime through accesscam.assets. The
    # filenames come from accesscam.ui.tray itself rather than being retyped
    # here - a hand-maintained list already drifted once: tray-trouble.png
    # existed and was wired into the tray for two commits before this list
    # was written, and was never added to it, so a packaged build silently
    # fell back to the drawn glyph for the one state that matters most.
    #
    # Third-party licence notices travel the same way, so an installed copy
    # never has to reach back to the GitHub repo to read what it is carrying.
    datas=[
        (str(ROOT / "assets" / name), "assets")
        for name in (*_art_filenames(), APP_ICON)
        if (ROOT / "assets" / name).is_file()
    ]
    + [
        (str(ROOT / "packaging" / "licenses" / name), "licenses")
        for name in _licence_filenames()
    ]
    + [
        (str(ROOT / "THIRD-PARTY-NOTICES.md"), "."),
        (str(ROOT / "LICENSE"), "."),
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
    uac_uiaccess=UIACCESS,
    icon=str(ROOT / "assets" / APP_ICON),
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
