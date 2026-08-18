# Building AccessCam

Two stages, run in order: PyInstaller freezes the Python application into a
folder, then Inno Setup wraps that folder into an installer. Neither is part
of the normal `pytest` / `ruff` loop - only run this when you actually need an
installable artifact.

```powershell
pip install -e ".[dev]"
pyinstaller packaging\accesscam.spec --noconfirm
```

That produces `dist\AccessCam\` - a one-folder build, `AccessCam.exe` plus
everything Qt and OpenCV need beside it. **Run it before going further**:
launch `dist\AccessCam\AccessCam.exe` directly and confirm the window opens,
the camera is found, and the tray icon appears. A build that doesn't do this
isn't worth wrapping in an installer.

Then, with [Inno Setup 6](https://jrsoftware.org/isdl.php) installed:

```powershell
& "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe" packaging\AccessCam.iss
```

(Or wherever ISCC.exe landed - a machine-wide install puts it under
`C:\Program Files (x86)\Inno Setup 6\` instead.) That produces
`dist\installer\AccessCam-Setup-<version>.exe`.

## What the installer does, briefly

Per-user install (`{autopf}` under `PrivilegesRequired=lowest`), so it needs no
administrator rights - matching AccessCam itself, which runs unelevated and
says so in its own window when that isn't enough (the elevation banner, M4.1).
Desktop and Start Menu shortcuts, plus a second Start Menu entry that starts
AccessCam elevated with no UAC prompt via the scheduled task, using the same
`tools/launch-elevated.vbs` John uses on his own machines.

Uninstall removes the logon task if one is registered - see the `[Code]`
section in `AccessCam.iss` and the M4.5 writeup in `docs/PROJECT_PLAN.md` for
why that's hand-written Pascal Script rather than a call into `startup.py`
(the uninstaller has no Python inside it). Config and log in
`%APPDATA%\AccessCam` are never touched by install or uninstall.

## UIAccess (not enabled yet — needs a certificate)

AccessCam needs to deliver input to higher-integrity windows (on-screen
keyboards, anything elevated), and today does it by running as administrator.
The better mechanism is **UIAccess**, Windows' accessibility exemption from
UIPI — the same one the SmartNav uses, via an external `smartnav.exe.manifest`
carrying `level="asInvoker" uiAccess="true"`. A process holding UIAccess needs
no admin rights and raises no UAC prompt.

The spec supports it already, opt-in:

```powershell
$env:ACCESSCAM_UIACCESS = "1"
pyinstaller packaging\accesscam.spec --noconfirm
```

**Do not set this until the exe is both signed and installed under Program
Files.** Windows grants UIAccess only to an Authenticode-signed binary in a
location standard users cannot write to. Fail either test and the process does
not start in a degraded mode — it does not start at all:

```
Start-Process : This command cannot be run due to the error:
A referral was returned from the server.
```

That is what an unsigned UIAccess build looks like, and it is why the flag is
off by default rather than always on. See `docs/PROJECT_PLAN.md` M4.8 for the
certificate and install-location decisions this waits on.

## Testing a change to the installer without touching the real logon task

`AccessCam.iss` matches the scheduled task by name (`AccessCam`), the same
name the real app's own "start at logon" checkbox registers. Compiling and
running the *real* script's uninstaller against a scratch install will still
try to remove whatever "AccessCam" task actually exists on the machine - which
on a development box is very possibly the one you rely on daily, and which
this session had no elevated shell available to re-register if that went
wrong.

To test uninstall logic safely, copy the script and change the task name and
output paths before compiling, so it operates on a name nothing else uses:

```powershell
Copy-Item packaging\AccessCam.iss packaging\AccessCamTest.iss
# edit the copy: TaskName = 'AccessCamUninstallTest'; different OutputDir
& ISCC.exe packaging\AccessCamTest.iss
# install and uninstall silently against that build, then delete the copy
```

Silent install/uninstall, useful for exactly this:

```powershell
Start-Process AccessCam-Setup.exe -ArgumentList '/VERYSILENT','/SUPPRESSMSGBOXES','/DIR=<path>','/LOG=<path>' -Wait
Start-Process <installdir>\unins000.exe -ArgumentList '/VERYSILENT','/SUPPRESSMSGBOXES','/LOG=<path>' -Wait
```

`/DIR=` and `/LOG=` both need a location the *current, unelevated* user can
actually write to - `C:\` root fails silently with exit code 1 and no log,
which looks identical to a genuine setup failure. Use `%LOCALAPPDATA%` or
`%TEMP%`.

The custom `[Code]` logic logs through Inno's own `Log()` procedure, which
lands in whatever file `/LOG=` points at - Inno's default logging does not
capture custom `[Code]`, so without those `Log()` calls a silent test run
looks identical whether the logon-task removal ran or was skipped entirely.
