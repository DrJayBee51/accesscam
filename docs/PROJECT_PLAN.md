# AccessCam Project Plan

## Goal

Replace a failing, discontinued NaturalPoint SmartNav 4 with an open-source
equivalent: an IR USB camera tracks a retroreflective dot worn by the user, and
a desktop application converts that motion into mouse cursor movement with
user-tunable gains, smoothing, and positioning mode, saved in named profiles.

Platform order: **Windows → Linux → macOS.**

## Decisions made (2026-08-08)

| Decision | Choice | Rationale |
|---|---|---|
| Stack | Python 3.11+ / OpenCV / NumPy / PySide6 | Fastest iteration; OpenCV blob tracking easily outruns the camera's 30fps; Qt gives a native cross-platform settings UI |
| v1 scope | Cursor movement only | User clicks by other means today; dwell click is v2 |
| License / visibility | MIT, public GitHub repo | Help other stranded SmartNav users; invite contributors |
| Camera (initial) | Arducam 1080P Day/Night USB (OV2710, 850nm IR LEDs) | Already owned; UVC so no drivers needed |

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
                 Qt UI: live preview, sliders, profile manager, tray icon
```

Planned module layout (`src/accesscam/`):

| Module | Responsibility |
|---|---|
| `camera.py` | Capture thread; enumerate devices; set resolution/fps/**exposure** via OpenCV/UVC; deliver frames |
| `tracker.py` | Threshold + contour/blob detection; return dot centroid (sub-pixel) and confidence; handle "dot lost" |
| `mapper.py` | Convert centroid motion to cursor motion. Relative mode: frame-to-frame delta × (H gain, V gain). Absolute mode: camera-space position → screen position through gains. Dead zone for micro-tremor |
| `smoothing.py` | One Euro filter (speed-adaptive: heavy smoothing when still, low lag when moving). The UI smoothing slider maps to its cutoff parameters |
| `mouse/` | Backend interface + `windows.py` (SendInput via ctypes). Later: `linux.py` (uinput/XTest), `macos.py` (Quartz) |
| `profiles.py` | Named profiles as JSON in the platform config dir (`%APPDATA%\AccessCam` on Windows); fields: h_gain, v_gain, smoothing, mode, dead zone, camera settings |
| `hotkeys.py` | Global pause/resume hotkey (essential — the cursor must be parkable) |
| `ui/` | PySide6: main window (preview + sliders + mode toggle + profile dropdown), tray icon, first-run camera picker |

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

### M2 — Cursor control engine
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

**Progress:** mouse backend ✅, mapper ✅, One Euro smoothing ✅, pause
hotkey ✅. Remaining: config file, and wiring `__main__.py` into a real
pipeline — which is first light.

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

### M3 — Desktop UI & profiles, and the production housing (parallel)
**Software:** PySide6 window: live preview with dot overlay, H/V gain sliders,
smoothing slider, relative/absolute toggle, profile save/load/switch, tray
icon, start-minimized and launch-at-login options.

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

**Exit criteria:** all settings adjustable live and persisted in named
profiles; app runs from the tray. Housing survives a day of normal use without
drifting out of aim, and the camera is captive.

### M4 — v1.0 release (Windows)
PyInstaller one-folder build, versioned GitHub Release, install/setup guide
with photos, printable STL + filter/dot instructions published in `hardware/`.

### M5 — v2 features
Dwell clicking (dwell time, click type, visual countdown), calibration wizard,
configurable hotkeys, optional gravity/precision mode near targets. (Basic
multi-monitor handling moved up to M2 — see there.)

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
