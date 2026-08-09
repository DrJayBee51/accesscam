# AccessCam

**An open-source head-tracking mouse, built to replace the discontinued NaturalPoint SmartNav.**

AccessCam uses an off-the-shelf IR USB camera to track a retroreflective dot (worn on the forehead, glasses, or a hat brim) and translates head movement into mouse cursor movement — restoring the workflow that SmartNav users depend on, with hardware that can actually be purchased and repaired.

## Status

🚧 **Early development.** Windows support is being built first, followed by Linux, then macOS. See [docs/PROJECT_PLAN.md](docs/PROJECT_PLAN.md) for the roadmap.

## How it works

```
IR LEDs illuminate a retroreflective dot → camera sees it as the brightest
blob in frame → OpenCV finds its centroid each frame → motion is scaled by
user-tunable gains, filtered for noise, and applied to the system cursor.
```

## Planned v1 features

- Track a retroreflective dot with a UVC IR camera (tested with the Arducam 1080P Day/Night B0205)
- **Horizontal & vertical gain sliders** — tune cursor speed/distance independently per axis
- **Smoothing slider** — One Euro filter to suppress jitter without adding sluggish lag
- **Relative or absolute positioning** toggle
- **Pause/resume hotkey** — park the cursor when you need to
- **User profiles** — save and switch between named settings profiles
- System tray app with live camera preview for aiming and diagnostics

## Planned for later versions

- Dwell clicking (hover-to-click) with configurable dwell time and click type
- Calibration wizard
- Linux support, then macOS support

## Hardware

- **Camera:** Arducam 1080P Day & Night Vision USB camera (OV2710, 6× 850nm IR LEDs) or any UVC camera that can see 850nm IR. See [docs/HARDWARE.md](docs/HARDWARE.md) for important setup notes (the IR-cut photoresistor must be shrouded).
- **Marker:** a small dot of retroreflective material (3M Scotchlite 7610 tape or equivalent — the same material SmartNav dots were made from).
- **Mount:** a 3D-printable monitor mount/housing, designed in SolidWorks (files will live in `hardware/`).

## Development setup

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
```

### Camera bring-up

Before there's a UI, `tools/camera_bringup.py` validates the hardware and tunes
tracking. It shows a live preview with the detected marker overlaid, and
measures the two numbers that set the app's defaults: how far the dot travels
across the sensor, and how much the tracked position jitters when you hold
still.

```powershell
python tools/camera_bringup.py --list      # find your camera's index
python tools/camera_bringup.py --device 0
```

Keys: `[` `]` adjust the brightness threshold, `-` `=` adjust exposure, `j`
measures jitter, `r` resets the travel range, `s` saves a snapshot, `q` quits
and prints a summary for the checklist in [docs/HARDWARE.md](docs/HARDWARE.md).

## License

[MIT](LICENSE)
