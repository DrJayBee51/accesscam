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

### M1 — Tracking prototype (software) & mount (hardware, parallel)
The two tracks meet at the end of M1: real tracking can't be validated until
the camera is mounted and a reflective dot is worn.

**Software:** ✅ `tools/camera_bringup.py` built — live preview, measured fps,
MJPEG/exposure control with clamp detection, threshold + sub-pixel blob
centroid overlay, and travel-range and jitter measurement.

**First real run against the Arducam (2026-08-09):**

| Measurement | Result | |
|---|---|---|
| Format / rate | 640×480 MJPG, **29.3fps** measured | ✅ |
| Exposure | requested −7, driver held −7.0 (no clamp) | ✅ |
| Photoresistor shroud | IR LEDs on in a lit room | ✅ |
| Marker travel | x 68.7px, y 48.1px | ⚠️ low |
| Jitter (stdev) | x 0.208px, y 0.195px | ✅ |

Threshold 200 isolated the dot at only −7 exposure, leaving headroom down to
−10 for brighter rooms. Two findings came out of the run: the Arducam
enumerates as **index 1** alongside a second webcam, and a FOURCC ordering bug
in `camera.py` was halving the frame rate (see HARDWARE.md).

**Travel is the weak number.** Dividing travel by jitter gives ~330
distinguishable horizontal positions and ~247 vertical — comfortable across a
single screen, thin across a large desktop. This drives the M2 scope below.
The 105° lens is the cause; crop/ROI or a closer mount would widen it.
**Hardware (SolidWorks):** monitor-top housing per `docs/HARDWARE.md` — must
shroud the IR-cut photoresistor, allow tilt aiming, and optionally hold an
IR-pass filter. Print, mount, and make a reflective dot (3M 7610 tape).
This first housing is deliberately a **development prototype**: the camera
slots in from above with no fasteners, so it can be pulled out and re-seated
freely during bring-up. `MonitorMountBase` replicates the SmartNav base (see
HARDWARE.md → *Mount base provenance*). Good enough to test with; not the
shipping design.
**Exit criteria:** dot tracked at a steady ~30fps at normal seating distance,
in daylight and lamplight, with jitter measured. *Remaining:* the run above
covered one lighting condition; repeat under daylight and lamplight to close.

### M2 — Cursor control engine
Mapper, One Euro smoothing, Windows SendInput backend, pause/resume hotkey,
config file (no UI yet — tune via config + hotkey reload).

**Relative mode is the priority; absolute is secondary.** The M1 travel figures
make this concrete. The target desktop is four 2560×1440 screens — 7680×3600
virtual — and 68.7px of dot travel has to cover it:

| Span | Gain | 0.208px jitter becomes |
|---|---|---|
| One screen (2560 wide) | 37 px/px | ~8px |
| Full desktop (7680 wide) | 112 px/px | ~23px |

⚠️ **Those extents are logical, DPI-scaled pixels**, read from a process that
was not DPI-aware. At least one display is physically 3840×2160 at 150%
scaling, and scaling may differ per monitor, so logical→physical is not one
constant. Re-measure the virtual desktop from a process that has called
`SetProcessDpiAwarenessContext(PER_MONITOR_AWARE_V2)` before fixing any default
gain. The ratios above still make the relative-vs-absolute argument — only the
absolute numbers are provisional.

At ~23px of cursor granularity, absolute mode cannot reliably land on small
targets across the full desktop — the mapping is fixed, so a miss stays missed.
Relative mode degrades gracefully instead: overshoot, then re-center and take a
second pass. This matches how the SmartNav is used today, in relative mode for
exactly this reason. Build and tune relative first; treat absolute as a
best-effort mode that is honest about being unsuited to a desktop this wide.

**Multi-monitor moves here from M5.** With a 7680px-wide desktop the gain that
suits one screen is 3× off for the whole thing, so it is a correctness concern
for the mapper rather than a later convenience. At minimum, decide whether
gains map to one screen or the whole virtual desktop, and make it configurable.

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
