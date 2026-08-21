# AccessCam Project Plan

## Goal

Replace a failing, discontinued NaturalPoint SmartNav 4 with an open-source
equivalent: an IR USB camera tracks a retroreflective dot worn by the user, and
a desktop application converts that motion into mouse cursor movement with
user-tunable gains, smoothing, and positioning mode.

*Named profiles were part of this sentence until 2026-08-15, written before
there was any usage to check it against. They moved to M5 — see there for why.*

Platform order: **Windows → Linux → macOS.**

## Decisions made (2026-08-08)

| Decision | Choice | Rationale |
|---|---|---|
| Stack | Python 3.11+ / OpenCV / NumPy / PySide6 | Fastest iteration; OpenCV blob tracking easily outruns the camera's 30fps; Qt gives a native cross-platform settings UI |
| v1 scope | Cursor movement only | User clicks by other means today; dwell click is v2 |
| License / visibility | MIT, public GitHub repo | Help other stranded SmartNav users; invite contributors |
| Camera (initial) | Arducam 1080P Day/Night USB (OV2710, 850nm IR LEDs) | Already owned; UVC so no drivers needed |
| **Camera (shipping default), 2026-08-18** | **The same Arducam B0205** | Confirmed rather than merely inherited, after months of daily use: it is sufficient for what AccessCam does and outperforms any comparable platform available today. The ELP model in `hardware/` was evaluated as an alternative and is not chosen. Anything UVC still works — this is the camera the housing is built around and the documentation assumes |

## Architecture

A processing pipeline running in a background thread, with a Qt UI observing it:

```
CameraSource ──► DotTracker ──► MotionMapper ──► Smoother ──► MouseBackend
 (capture        (find the      (px delta →      (One Euro     (move the
  thread,         brightest      cursor delta;    filter)       OS cursor)
  UVC controls)   blob           gains; relative/
                  centroid)      absolute)
                       │
                       ▼
                 Qt UI: live preview, sliders, tray icon
```

Planned module layout (`src/accesscam/`):

| Module | Responsibility |
|---|---|
| `camera.py` | Capture thread; enumerate devices; set resolution/fps/**exposure** via OpenCV/UVC; deliver frames |
| `tracker.py` | Threshold + contour/blob detection; return dot centroid (sub-pixel) and confidence; handle "dot lost" |
| `mapper.py` | Convert centroid motion to cursor motion. Relative mode: frame-to-frame delta × (H gain, V gain). Absolute mode: camera-space position → screen position through gains. Dead zone for micro-tremor |
| `smoothing.py` | One Euro filter (speed-adaptive: heavy smoothing when still, low lag when moving). The UI smoothing slider maps to its cutoff parameters |
| `engine.py` | Owns the pipeline and runs it on its own thread; publishes a status snapshot and the latest frame, and retunes live via `apply()`. Front ends observe it rather than containing it — a Qt event loop has to own the main thread, so the pipeline cannot |
| `mouse/` | Backend interface + `windows.py` (SendInput via ctypes). Later: `linux.py` (uinput/XTest), `macos.py` (Quartz) |
| `config.py` | Settings as flat JSON in the platform config dir (`%APPDATA%\AccessCam` on Windows); unknown keys ignored rather than fatal. Named profiles on top of this are M5 |
| `hotkeys.py` | Global pause/resume hotkey (essential — the cursor must be parkable) |
| `ui/` | PySide6: main window (preview + sliders + mode toggle), tray icon, first-run camera picker |

**Latency budget:** at 30fps a frame arrives every 33ms; processing must stay
trivially small next to that (blob detection on a thresholded frame is <1ms).
The dominant latency is the camera itself — which is why exposure should be
kept short and why a faster camera is the single best future upgrade.

## Milestones

### M0 — Project setup ✅ (2026-08-08)
Repo scaffolded, plan and hardware docs written, GitHub repo published.

### M1 — Tracking prototype (software) & mount (hardware) ✅ (2026-08-10)
The two tracks met as planned: real tracking could not be validated until the
camera was mounted and a reflective dot worn.

**Software:** ✅ `tools/camera_bringup.py` built — live preview, measured fps,
MJPEG/exposure control with clamp detection, threshold + sub-pixel blob
centroid overlay, and travel-range and jitter measurement.

**Bring-up runs:**

| Run | Light | fps | Exposure | Travel x/y (px) | Jitter x/y (px) |
|---|---|---|---|---|---|
| 2026-08-09 22:46 | lamplight | 29.3 | −7 | 68.7 / 48.1 | 0.208 / 0.195 |
| 2026-08-10 11:35 | daylight | 29.5 | −9 | 41.4 / 17.5 | 0.041 / 0.123 |
| 2026-08-10 12:2x | daylight | 28.8 | −9 | 1.2 / 3.2 | — |
| **2026-08-10 12:5x** | **daylight** | **29.3** | **−9** | **82.8 / 44.3** | **0.073 / 0.045** |

Read the last row as the trustworthy one. The two middle runs were corrupted by
a tracking bug, not by lighting: `_select` chose the largest blob on
acquisition, so a bright daylight object took the track and `max_jump` then
defended it, leaving the marker permanently ineligible. Travel collapsed toward
zero because the tracked object never moved. Fixed by filtering on shape and
ranking on brightness — see the commit and HARDWARE.md.

**Exposure matters twice over.** −9 was needed in daylight against −7 at night,
and the shorter exposure also *improved precision* 3–5×. The intensity-weighted
centroid needs a brightness gradient across the blob to work with; at longer
exposures the marker saturates into a plateau of 255s and the weighting
degenerates toward a plain geometric centroid. Default to the shortest exposure
that still holds the dot, not merely one that works.

**Effective resolution:** travel ÷ jitter gives ~1130 distinguishable
horizontal positions and ~980 vertical — 3–4× better than the first night's
figures, and enough to make relative-mode mapping comfortable. Horizontal and
vertical gains also came out within 5% of each other on this run, where earlier
runs disagreed by 60%; another sign the earlier travel figures were
contaminated rather than merely noisy.
**Hardware (SolidWorks):** monitor-top housing per `docs/HARDWARE.md` — must
shroud the IR-cut photoresistor, allow tilt aiming, and optionally hold an
IR-pass filter. Print, mount, and make a reflective dot (3M 7610 tape).
This first housing is deliberately a **development prototype**: the camera
slots in from above with no fasteners, so it can be pulled out and re-seated
freely during bring-up. `MonitorMountBase` replicates the SmartNav base (see
HARDWARE.md → *Mount base provenance*). Good enough to test with; not the
shipping design.
**Exit criteria:** ✅ dot tracked at a steady ~30fps at normal seating distance,
in daylight and lamplight, with jitter measured. All met — 29.3–29.5fps across
every run, tracked under lamplight at −7 and daylight at −9 with no exposure
clamping, jitter measured in both.

### M2 — Cursor control engine ✅ (2026-08-15)
Mapper, One Euro smoothing, Windows SendInput backend, pause/resume hotkey,
config file (no UI yet — tune via config + hotkey reload).

**Relative mode is the priority; absolute is secondary.** The M1 travel figures
make this concrete. The target desktop is four 2560×1440 screens — 7680×3600
virtual — and 82.8px of dot travel has to cover it:

| Span | Gain | 0.073px jitter becomes |
|---|---|---|
| One screen (2560 wide) | 31 px/px | ~2px |
| Full desktop (7680 wide) | 93 px/px | ~7px |

**Verified against the real desktop (2026-08-10), DPI-aware.** 7680×3600 with
its origin at (−2560, −2160) is the true extent in *physical* pixels —
`GetSystemMetrics` returns the same values with and without per-monitor
awareness, so the gain figures above stand. An earlier draft of this section
claimed they were DPI-scaled and needed re-measuring; that was wrong.

The setup is nonetheless **mixed-DPI**, which is why awareness still matters:

| Display | Origin | Physical | Scale |
|---|---|---|---|
| DISPLAY1 (top) | (0, −2160) | 3840×2160 | 150% |
| DISPLAY3 (left) | (−2560, 0) | 2560×1440 | 100% |
| DISPLAY4 (primary) | (0, 0) | 2560×1440 | 100% |
| DISPLAY2 (right) | (2560, 0) | 2560×1440 | 100% |

A process that has not called `SetProcessDpiAwarenessContext` sees DISPLAY1 as
2560×1440, so it must be called before any metrics call.

At ~7px of cursor granularity across the full desktop, absolute mode is not
disqualified on resolution alone — an earlier draft of this section said it was,
based on the contaminated travel figures. What still argues against it is that
its mapping is fixed, so a miss stays missed, and that the four screens cover
only ~70% of the virtual bounding box: absolute mapping aims at coordinates
that may not be on any monitor, and Windows then snaps the cursor to the
nearest screen. Relative mode degrades gracefully instead —
overshoot, then re-center and take a second pass. This matches how the SmartNav
is used today, in relative mode for
exactly this reason. Build and tune relative first; treat absolute as a
best-effort mode, and expect it to need a screen-selection choice rather than a
naive map onto the whole virtual desktop.

**Multi-monitor moves here from M5.** With a 7680px-wide desktop the gain that
suits one screen is 3× off for the whole thing, so it is a correctness concern
for the mapper rather than a later convenience. At minimum, decide whether
gains map to one screen or the whole virtual desktop, and make it configurable.

**Progress (2026-08-10):** mouse backend ✅, mapper ✅, One Euro smoothing ✅,
pause hotkey ✅, config ✅, pipeline ✅. `python -m accesscam` drives the
cursor, and it is running on both the development and work machines.

Tuned by use rather than theory on first light: `h_gain` 100, `v_gain` 70,
`min_cutoff` 0.15, `beta` 0.4, `max_step` 2500. Three things came out of that
session — a `max_step` of 400 was truncating fast gestures so they travelled
less far than slow ones over the same ground, the cursor accumulated movement
into screen regions belonging to no monitor, and hover-driven UI needs
AccessCam run as administrator.

**Signed off (2026-08-15).** The exit criterion was a comfortable 15+ minutes of
real work; what actually happened was **four consecutive days of 8+ hours** on
the work PC, as the daily driver, across three screens. That is the criterion by
two orders of magnitude. Two problems came out of it, both now fixed:

- **A daylit office window rivalled the marker** and stole the track. Neither
  shape nor brightness filtering can reject a window, so blobs outside an opt-in
  region of interest are now excluded entirely.
- **Jitter at slow speeds was tiring over a full day**, and made holding a caret
  still for text selection hard. The smoother was already at its floor, so the
  fix had to be in the gain: it is now scaled down while the marker is nearly
  still. See *Holding the cursor still* in RUNNING.md.

Both were found by use and neither was predictable from the bench. The pattern
worth keeping for M3: ship the smallest thing that can be lived with, then live
with it for a week before deciding what is wrong.

**Per-machine settings have diverged** — different screen counts, different
lighting, different gains. Both machines' settings are recorded in RUNNING.md,
one block each.

This briefly looked like an argument for named profiles. It is not: `%APPDATA%`
is already per-machine, so the two installations never collide. What actually
hurts is carrying settings between a development PC and a work PC through a
*repository*, which is a build-workflow problem and does not exist for anyone
who installs the app once. See M5.

The hotkey is a bare **F9** rather than a modifier chord because the fallback
input when the cursor is unusable is a mouth-operated QuadStick with F9 already
mapped; a chord would not be reachable from it. `parse_hotkey` therefore
permits unmodified *function* keys while still rejecting bare letters and
digits, which a global hotkey would swallow system-wide. Verified with 8 of 8
physical presses: correct alternation, no key-repeat storms, clean unregister.

**AccessCam claims F9 globally while running**, so nothing else on the system
receives it. SmartNav had F9 mapped and was remapped to F6 to free it.

Two things cost a long debugging detour and are worth not rediscovering:

- **A rival low-level keyboard hook consumes the key without making
  registration fail.** SmartNav claimed F9 with a `WH_KEYBOARD_LL` hook rather
  than `RegisterHotKey`, so ours registered successfully and then received
  nothing. If a hotkey registers cleanly but never fires, suspect another
  application's hook, not the registration.
- **Software-injected keystrokes do not drive `RegisterHotKey`.** A hook saw a
  synthetic F9 arrive with `LLKHF_INJECTED` set while no `WM_HOTKEY` was
  delivered. `SendInput` cannot test this path; only physical presses can.

**Exit criteria:** daily-drivable cursor control from the tracked dot in
relative mode; the user can navigate their desktop comfortably for 15+ minutes,
including moving between monitors.

### M3 — Desktop UI and the production housing (parallel)
**Software:** PySide6 window: live preview with dot overlay, H/V gain sliders,
smoothing slider, acceleration controls, relative/absolute toggle, tray icon,
start-minimized and launch-at-login options.

**Progress (2026-08-16).** The pipeline moved out of `app.run` into
`engine.py`, which runs it on its own thread and publishes a status snapshot —
a Qt event loop has to own the main thread, so the pipeline could not stay
where it was. On top of that, all ✅:

- The three-tab window behind `--ui`, with live preview, a draggable region
  picker, the acceleration curve plotted live, and help behind question marks
- Tray icon that carries state — green driving, red parked — with closing the
  window hiding to it rather than quitting
- *Application* tab: camera selection with rescan, start-minimised, start at
  logon, and a confirmed Quit
- A **first-run camera picker** (2026-08-16). The picker in the Application tab
  sat behind a successful start, so a machine where the stored index is wrong —
  which is most machines on a first run, since `device` defaults to 0 and a
  built-in webcam habitually takes it — ended at "could not start" with no way
  past. Failing to open the camera now offers the list instead of exiting, and
  remembers the answer. Operable entirely from the keyboard, because the person
  meeting this dialog does not have a working pointer yet

**Launch-at-login is a scheduled task, not the usual registry Run key.**
AccessCam wants to be elevated (UIPI, see RUNNING.md) and a Run entry cannot
elevate, so `startup.py` registers `schtasks /rl highest /sc onlogon`. Creating
it needs admin, so the checkbox reports what is actually registered rather than
what was asked for. It targets `pythonw.exe` deliberately: `python.exe` is a
console application and would put a black box behind the window at every logon.

Still outstanding:

- **The relative/absolute toggle.** Lowest value of what is left — absolute is
  best-effort and needs a screen-selection decision before a toggle means much.
- **Ten settings unreachable** from the window: `backend`, `width`,
  `height`, `fps`, `max_jump`, `d_cutoff`, `invert_x`, `invert_y`, `dead_zone`,
  `max_step`. `invert_x`/`invert_y` are two cheap checkboxes and
  mount-dependent; the rest are advanced. **`hotkey` came off this list on
  2026-08-21** - it is a dropdown on the Application tab, pulled forward from
  M5 because editing JSON to change the one key that parks the cursor was a
  poor answer for the people this ships to.
- **Single-instance detection.** A second instance cannot open the camera and,
  launched by the logon task under `pythonw` with no console, dies without
  saying anything. Harmless at logon, but it needs handling before M4 ships to
  anyone else — either refuse politely or hand focus to the running instance.

**The exit criterion below needs rewording before it can be met.** It asks for
every setting to be adjustable, but the camera
settings cannot be live at all: changing `device`, `width`, `height` or `fps`
means closing and reopening the capture, which `Engine.apply` deliberately
refuses. "Every setting that can be changed without reopening the camera" is
the achievable version.

**No profile management here** — it moved to M5 on 2026-08-15. The single
settings file is enough for a machine with one user, which is every
installation that exists. See M5 for the reasoning and the design.

**Hardware (SolidWorks) — production housing.** Supersedes the M1 slot-in
prototype, now that development testing has settled the camera position, tilt
angle, and filter choice. Must add what the prototype deliberately skipped:

- Captive board mounting (M2 screws or snap posts) instead of the open slot
- A retention feature so the camera cannot fall out when the monitor is bumped
- Tilt adjustment that *holds* its setting — friction hinge or notched detents,
  ±20° pitch (HARDWARE.md req 3)
- Clamp or counterweight on `MonitorMountBase` spanning the full 10–40mm bezel
  range, plus a fastened interface to `HousingBottom` (the prototype has
  neither; it is a fixed ~29mm perch that simply rests in place)
- Strain relief for the USB pigtail, and vents
- Rebuild in **MMGS** — the prototype inherits inch units from the traced
  SmartNav base, but nothing downstream of it needs to

**Exit criteria:** all settings adjustable live and persisted; app runs from the
tray. Housing survives a day of normal use without drifting out of aim, and the
camera is captive.

### M4 — v1.0 release (Windows)
PyInstaller one-folder build, versioned GitHub Release, install/setup guide
with photos, printable STL + filter/dot instructions published in `hardware/`.

**Remaining work, itemised** (re-surveyed against the code 2026-08-18). Done
means the line after "Done:" is true, not that the work felt finished.

#### Blocking — the release is broken or unshippable without these

**M4.1 — Say in the window when it is not elevated.** ✅ *Done 2026-08-18.*
`warn_if_not_elevated()` is called once, at `app.py:127`, inside the *headless*
`run()`. The UI path only writes elevation to the log. A packaged app has no
console at all, so someone who double-clicks the exe gets an install where the
cursor moves but every hover-driven window ignores it — the failure that took
longest to attribute the first time anyone met it, and the one least likely to
be reported as a bug rather than abandoned.
*Done: the window says so unmissably while unelevated, and offers the fix.*

**M4.2 — Single-instance detection.** ✅ *Done 2026-08-18.* Nothing implements it (searched:
no mutex, no lock). A second copy waits `--wait-for-camera` seconds for a
camera the first copy holds, then blames the hardware in a dialog. Under the
logon task with `pythonw` it dies with no console at all. A named mutex is the
usual answer; the choice worth making is whether the second copy exits quietly
or hands focus to the first, and the latter is what a user double-clicking a
shortcut twice actually means.
*Done: launching twice surfaces the running instance and never accuses the camera.*

**M4.3 — The build.** ✅ *Done 2026-08-18.* `packaging/accesscam.spec`
produces a one-folder PyInstaller build (262MB unpacked) with a real Windows
version resource - the first attempt used `version_info={"version": ...}`,
which `EXE()` accepts silently and does nothing with, so the shipped exe had a
blank Properties > Details tab until this was caught and replaced with the
`VSVersionInfo` structure PyInstaller actually reads.

One folder rather than one file, deliberately: `--onefile` unpacks itself to a
temp directory on every launch, which costs seconds at exactly the moment
AccessCam is already racing the camera and the shell at logon, and leaves
antivirus software watching an executable materialise from nowhere at every
boot.

**The first build found a real bug**: `--ui` was never the default, so a
double-clicked `AccessCam.exe` opened *nothing* - no window, no tray - while
quietly taking over the pointer. `wants_ui()` in `app.py` now opens the window
whenever `sys.frozen` is set, unless `--headless` says otherwise; a source
checkout keeps the old default, since `python -m accesscam` is how the
pipeline gets exercised without a UI in the way. Verified from the built exe,
not from source: camera opened, window built, tray icon shown, hotkey
registered.

No release job in CI yet - left for whenever tagged releases start.
*Done: a one-folder build launches on a Windows machine that has never had
Python, opens the camera, and registers the logon task from the checkbox.*

**M4.4 — Decide the distribution shape.** ✅ *Decided 2026-08-18: an **Inno
Setup installer**.* It is the only shape that can satisfy M4.5, since a zip
leaves nothing behind to remove the logon task, and the people this is for are
often installing with someone's help — where "unpack it and find the exe" is
the step that goes wrong. Free, scriptable, and runnable in CI.

**The installed application does not require administrator rights**, and that
is deliberate rather than an oversight. AccessCam wants them, but demanding
them in the manifest would lock out anyone who is not an administrator of their
own machine — a real case in the schools and centres this is aimed at. It runs
as whoever launched it, says so in the window when that is not enough (M4.1),
and offers the scheduled task as the way up.

**M4.5 — Uninstall has to remove the logon task.** ✅ *Done 2026-08-18, built
into the same installer as M4.3/M4.4.* `packaging/AccessCam.iss` writes
`[Code]` rather than calling `startup.disable()` - the uninstaller is a
separate generated exe (`unins000.exe`) with no Python inside it, so the logic
is reimplemented directly in Pascal Script: try `schtasks /delete` unelevated
first, and only if the task survives that, prompt for elevation with
`ShellExec('runas', ...)` - the same on-demand-elevation pattern
`relaunch_elevated()` already uses, rather than requiring the whole
uninstaller to run as administrator. If both attempts fail, it says so and
gives the manual command rather than leaving a silent mess; a `MsgBox` at that
point is guarded by `UninstallSilent()`, since an unattended uninstall (an IT
deployment script, say) must never block on a dialog nobody is watching to
click.

Config and log in `%APPDATA%\AccessCam` are deliberately left alone -
`[UninstallDelete]` only targets the install directory. Settings tuned over
days of real use are not the installer's to discard.

**Verified end to end, with one deliberate exception.** Silent install and
uninstall were run against an isolated build with the task name swapped to a
throwaway value, confirming: the "no task registered" path exits cleanly with
no dialog (the common case - most users never enable logon start), the custom
Pascal code actually runs (confirmed via `Log()` lines in the Inno-generated
log, which does not capture custom `[Code]` by default), and no file outside
the install directory is touched. **Not verified**: actually deleting a
registered `/rl highest` task, because creating one to delete requires an
elevated shell, and this session had none to spare - test-registering even a
*non-elevated* task failed with Access Denied here, tighter than the
create-only restriction `startup.py` already documented. Deleting the one real
task on this machine to test against was ruled out: it is John's live logon
task, and there was no way to re-register it elevated afterward if the test
went wrong. Worth a five-minute real check next time the installer runs on a
machine with the task already set.
*Done: removing AccessCam leaves no scheduled task and no broken shortcuts.*

**M4.6 — Third-party licences.** ✅ *Done 2026-08-18.* `THIRD-PARTY-NOTICES.md`
covers what a build actually ships - PySide6/shiboken6 (LGPL-3.0-only, chosen
from Qt's dual/triple licence rather than GPL or commercial), OpenCV
(Apache-2.0 core, MIT wrapper), NumPy (BSD-3-Clause) - with the LGPL relinking
question answered rather than waved at: AccessCam's build is one-folder
specifically so Qt's DLLs sit beside `AccessCam.exe` as ordinary, unmodified,
replaceable shared libraries, which is exactly the "suitable shared library
mechanism" LGPLv3 §4(d)(1) describes as satisfying the licence without
requiring source to be conveyed. Worth knowing this reasoning connects back to
the M4.3 packaging-format decision, made for unrelated reasons, that happened
to make the licensing question easy to answer honestly.

The verbatim licence texts are vendored in `packaging/licenses/` - fetched
directly (not through a summarising tool) for the LGPL-3.0 text Qt's own wheel
does not include, and copied whole from the installed wheels for OpenCV and
NumPy rather than hand-curated, so a future third-party component either of
them bundles is not silently dropped. Both the frozen build (via the
PyInstaller spec) and the installer (via `AccessCam.iss`, at the install root
rather than buried under PyInstaller's `_internal\`, or the whole point is
defeated) ship the notices and every licence file.

A real gap turned up while wiring the build: the PyInstaller spec's artwork
list still named only two of the three tray states, two commits after the
third state was built - `tray-trouble.png` was never bundled, so a packaged
build would have silently fallen back to the drawn glyph for the one state
that matters most. Fixed by having the spec read the filenames from
`accesscam.ui.tray.TRAY_ART` itself rather than a second, driftable list.

`tools/check_licenses.py` (wired into CI as its own job) cross-checks
`pyproject.toml`'s declared runtime dependencies, each package's actual
installed licence metadata, and what `THIRD-PARTY-NOTICES.md` and
`packaging/licenses/` claim - catching a dependency added without a licence
entry, a vendored file going missing, or a package quietly relicensing between
versions, none of which a passing test suite would ever notice on its own.
*Done: a `THIRD-PARTY-NOTICES` file ships in the artifact, and the LGPL
relinking question is answered explicitly rather than ignored.*

#### Needed before anyone else is asked to install it

**M4.7 — Report a version.** ✅ *Done 2026-08-18.* `__version__ = "0.1.0"` exists in `__init__.py`
and is surfaced nowhere: no `--version`, no About. It is also duplicated in
`pyproject.toml`, so the two can disagree. A bug report against "AccessCam" with
no version is nearly useless.
*Done: one source of truth, reachable from both the command line and the window.*

**M4.8 — Code signing: SmartScreen, and the elevation problem it also solves.**
Reframed 2026-08-18 after looking at how the SmartNav actually does this, which
turned out to answer a question M4.1 and M4.4 had settled the hard way.

**The finding.** The SmartNav does not run as administrator. Its
`smartnav.exe.manifest` — an *external* manifest beside the exe, which is why a
search for an embedded one comes up empty — asks for:

```xml
<requestedExecutionLevel level="asInvoker" uiAccess="true"/>
```

`uiAccess="true"` is Windows' official accessibility exemption from UIPI. A
process holding it runs at ordinary privilege — no admin, no UAC prompt, works
for a user who is not an administrator of their own machine — and is still
allowed to deliver input to higher-integrity windows. It is precisely the
mechanism this application should be using, and what assistive technology is
*meant* to use.

Windows grants it only when all three hold, and the SmartNav satisfies all
three (verified on this machine 2026-08-18):

| Requirement | SmartNav |
|---|---|
| `uiAccess="true"` in the manifest | yes |
| Authenticode-signed by a trusted publisher | yes — GlobalSign, "NaturalPoint, Inc" |
| Installed under Program Files or System32 | yes — `C:\Program Files (x86)\NaturalPoint\` |

The signature and the protected location are the security argument: a standard
user cannot write to Program Files, so nobody can claim the exemption for a
binary they dropped on the desktop, and the certificate says who built it.

**Why this makes one certificate buy two things.** Signing was already on this
list to stop SmartScreen's "Windows protected your PC" on first launch. The
same certificate also unlocks UIAccess, which removes the elevation problem
outright: no administrator rights, no UAC prompt (unanswerable by a head-tracked
cursor, per M4.1), and no scheduled task needed *for elevation* — the task stays
useful only for starting at logon. It also dissolves the tension M4.4 recorded:
AccessCam would work for a non-admin user at a school or rehab centre without
anyone elevating anything, which `requireAdministrator` would have made
impossible.

**Already prepared, so the day a certificate exists this is a short job:**

- `packaging/accesscam.spec` takes `uac_uiaccess` from `ACCESSCAM_UIACCESS=1`,
  opt-in and off by default. It **has** to be opt-in: Windows does not launch a
  `uiAccess="true"` binary that fails the signing or location test in some
  degraded mode, it refuses to start it at all — "A referral was returned from
  the server", verified against an unsigned build. Unconditional would mean a
  build nobody can run until the certificate is bought.
- `mouse/windows.py` grew `has_uiaccess()` (reads `TokenUIAccess` from the
  process token) and `can_reach_privileged_windows()`, and the M4.1 banner asks
  the combined question. A signed, properly installed AccessCam holding UIAccess
  is not running as administrator and does not need to be, so telling that user
  to restart elevated would be crying wolf.

**Proven end to end on 2026-08-18, with a self-signed certificate.** Before
spending anything on a real one, the whole mechanism was tested: a self-signed
code-signing certificate, its root imported into `LocalMachine\Root`, the
UIAccess build signed with it, and the result installed to
`C:\Program Files\AccessCam-UIAccessTest\`. Launched **unelevated**, AccessCam
logged:

```
elevated: False   uiaccess: True
```

So Windows does not require a *commercially* trusted certificate — only one the
machine trusts. Three things follow:

- **The mechanism works for AccessCam specifically**, not just in principle. No
  admin rights, no UAC prompt, no scheduled task, and the M4.1 banner correctly
  stays hidden because `can_reach_privileged_windows()` sees UIAccess.
- **A certificate can be deferred without deferring the benefit on known
  machines.** Signing with a self-signed certificate trusted on John's own PCs
  would give him UIAccess today. It does nothing for anyone else - a stranger's
  machine would not trust it, so a distributed build still needs a real
  certificate - and it means trusting a self-signed root machine-wide, which is
  a real if small risk: anyone holding that private key could sign anything the
  machine would then trust.
- **The remaining unknown is only reputation and reach**, not capability. What a
  purchased certificate buys is SmartScreen (M4.8's original purpose) and the
  ability for *other people* to get UIAccess. It is no longer a question of
  whether the approach works.

**Still to decide, and both cost something:**

1. **The certificate itself.** Roughly $100–400/year for a standard OV
   certificate. An EV certificate clears SmartScreen immediately rather than
   after building reputation, and costs more.
2. **Install location.** UIAccess requires Program Files, but the installer is
   currently per-user (`PrivilegesRequired=lowest`) precisely so it needs no
   admin. A machine-wide install needs administrator rights **once, at install
   time** — the same trade the SmartNav makes, and a normal thing for IT to do —
   in exchange for never needing them again. Worth offering both: a per-user
   install that works unelevated without UIAccess, and a machine-wide one that
   gets it.

*Done: either signed — with UIAccess enabled and the install location decided —
or the SmartScreen warning documented at the point the user meets it.*

**M4.9 — The README is stale.** It still says "There is no UI yet — you
configure it with a JSON file", which is the front page of a repository whose
whole point by then is a downloadable application.
*Done: the front page describes what M4 actually ships.*

**M4.10 — Install and setup guide with photos.** `docs/RUNNING.md` is written
for someone with a clone, a venv and a terminal. The installing user has an
exe, a camera in a box, and a piece of reflective tape.
*Done: a guide that starts at "download this" and ends at a moving cursor.*

#### Known gaps that M4 consciously ships with

- ~~The hotkey can only be changed by editing JSON.~~ ✅ Done 2026-08-21:
  a dropdown of F1–F24 on the Application tab, which falls back to the previous
  key if the new one is already held by another program.
- **Eleven settings remain unreachable from the window** (M3 lists them).
- **Relative mode only**; absolute still needs a screen-selection decision.

#### The hardware half

**The camera is decided: the Arducam B0205, as of 2026-08-18.** It is
sufficient for what AccessCam does and outperforms any comparable platform on
sale, and it has months of daily use behind it rather than a spec sheet. The
ELP model stays in `hardware/` as an evaluated alternative, not a candidate.
That unblocks the production housing, which can now be dimensioned against one
camera instead of hedging between two.

What remains is the M3 production housing itself, which has not been started —
still the M1 slot-in prototype. M4 then needs the printable STL, the filter and
dot instructions, and the bezel range published alongside the software.

### M5 — v2 features
Dwell clicking (dwell time, click type, visual countdown), calibration wizard,
optional gravity/precision mode near targets. (Configurable hotkeys were pulled forward to M3 on 2026-08-21.) (Basic
multi-monitor handling moved up to M2 — see there. Note that the M2
acceleration curve may have already covered most of what a precision mode was
for, so re-examine that item before building it.)

#### Named profiles — deferred here from M3 (2026-08-15)

**Why they were deferred.** Profiles were in the goal statement from
2026-08-08, written before there was any usage to check them against. Three
things emerged once there was:

- **The user of the device this replaces never used the feature.** That is the
  best evidence available, and it outweighs speculation.
- **Per-machine settings need no profiles.** `%APPDATA%` is already per-machine,
  so two installations are separate by construction. The pain that made profiles
  look urgent was syncing a *repository* between a development PC and a work PC:
  a build-workflow problem, not a product one.
- **Profiles have no user until M4 ships.** Their justification is shared
  institutional machines, and no institution can install this before there is
  an installer.

**Why they are not cancelled.** The testing centre at the user's college ran
SmartNav on a **single shared desktop login**, which is the one case Windows
user accounts do not already solve. Rehab centres and assessment stations are
the same shape. Real, but institutional, and worth building when an institution
asks rather than in anticipation.

**The constraint that case imposes — this is the part worth not rediscovering.**
At a testing centre a proctor sets up for someone who cannot use the mouse yet.
A profile picker operated *with the cursor* is therefore useless to the person
who needs it: selecting the profile requires the working cursor that selecting
the profile is meant to provide. Profile selection has to happen at **launch**,
not inside the settings window — a `--profile` flag, a per-user desktop shortcut
a proctor configures once, or a first-screen picker reachable from the keyboard
or a QuadStick. Same single-key-reachable reasoning that made the pause hotkey a
bare F9.

**Storage design, already worked out.** A profile is just a named config file,
so this is a naming and selection layer rather than a new schema — `Config.load`
and `Config.save` already take an optional path:

```
%APPDATA%\AccessCam\
  config.json              <- untouched; unchanged behaviour when no profiles exist
  active.json              <- {"profile": "work"}
  profiles\<name>.json
```

Resolution order, first match wins:
`--config PATH` → `--profile NAME` → `active.json` → `config.json` → defaults.

Purely additive, with no automatic migration: silently rewriting the config of a
tool someone depends on for computer access is a bad trade against the risk in
the table below. Opting in means running `--save-profile` once.

Keep profiles **flat** — every key in every file, identical to `Config` — and
document `device` as the one value to fix when copying between machines. The
alternative, splitting machine-level keys into their own file, invents a second
schema and a merge step to solve one integer.

Profile names become filenames, so validate them: `[A-Za-z0-9_-]`, 1–64
characters, and reject the Windows reserved device names (`con`, `prn`, `aux`,
`nul`, `com1`–`com9`, `lpt1`–`lpt9`) case-insensitively. `con` passes a naive
character check and then fails at `open()` in a way that is hard to diagnose.

### M6 — Linux port
`uinput`-based mouse backend (evdev), packaging (AppImage or Flatpak),
Wayland/X11 notes. UVC camera and OpenCV already work there.

### M7 — macOS port
Quartz event mouse backend, camera permission handling, notarized .app bundle.

## Risks & mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| 30fps camera ceiling (OV2710) | Less smooth than SmartNav's ~100Hz | One Euro filter tuned per-user; run at 640×480 MJPEG for lowest latency; document upgrade path (Arducam OV9281 global-shutter, 120fps, ~$40 — software is camera-agnostic via UVC) |
| Auto IR-cut engages in lit rooms, blocking IR | Tracking dies in daylight | Housing shrouds the photoresistor to force night mode (see HARDWARE.md) |
| Bright room objects (windows, lamps) rival the dot | False tracking | Short exposure + optional 850nm IR-pass filter; blob size/shape filtering; track nearest-to-last-position |
| Python 3.14 wheel availability (OpenCV/PySide6) | Setup friction | Pin to Python 3.12 in the venv if 3.14 wheels lag; `requires-python >=3.11` keeps options open |
| The user's daily driver breaks while the SmartNav degrades | Lost computer access | Keep milestones small; M2 already yields a usable fallback device |

## Out of scope (for now)

Eye/gaze tracking, face-feature tracking without a marker (OpenTrack/eviacam
territory), game head-look (TrackIR protocol), mobile/iOS.
