# Running AccessCam

How to get the cursor moving on a machine that has never run it. Written for
Windows, which is the only platform with a mouse backend so far.

## What you need

- The Arducam and its printed housing, mounted on top of a monitor and plugged
  into **this** machine's USB
- A retroreflective dot on your forehead, glasses, or hat brim
- Python 3.11 or newer

## 1. Install

```powershell
git clone https://github.com/DrJayBee51/accesscam.git
cd accesscam
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e .
```

## 2. Find the camera

The index differs from machine to machine, and a built-in webcam often takes 0.

```powershell
python -m accesscam --list-devices
```

The Arducam is the one that grants **1920x1080**; lower-resolution webcams will
not. Then save it:

```powershell
python -m accesscam --device 1 --write-config
```

That writes `%APPDATA%\AccessCam\config.json`, which you can edit by hand
afterwards — every value is in there, and anything you leave out falls back to
its default.

## 3. Check the shroud before anything else

Cover the photoresistor on the camera board and confirm the **IR LEDs glow
faintly red** with the room lights on. If they do not, the board is in day
mode, the IR-cut filter is blocking 850nm, and no amount of software tuning
will make tracking work. See [HARDWARE.md](HARDWARE.md).

## 4. Dry run

```powershell
python -m accesscam --dry-run
```

This runs the entire pipeline but never touches the real cursor. You want to
see:

- `640x480 MJPG` — if it says anything else the frame rate will suffer
- `29-30fps` — the camera's real ceiling
- `tracking` and `lost 0%` — the marker is being found
- `pause hotkey: F9` registered

If `lost` is high, the marker is not being seen: check the shroud, and try a
shorter exposure with `--exposure -10`.

## 5. First light

```powershell
python -m accesscam
```

It **starts paused**. Press **F9** to take control, F9 again to park the
cursor. Ctrl+C in the terminal quits.

Expect to want a different gain immediately. Edit `h_gain` and `v_gain` in the
config: higher means the cursor travels further for the same head movement.
The defaults of 31 and 32 are calibrated for one 2560x1440 screen.

## Safety

The cursor is driven with no window to click on, so **F9 is the way out**. It
is a bare function key rather than a chord specifically so it is reachable from
a QuadStick or similar fallback device. Keep a fallback input available the
first few times you run this.

If the cursor becomes unusable and F9 does not respond, Ctrl+C in the terminal
stops the program, and closing the terminal window kills it outright.

## Tuning

| Symptom | Setting | Direction |
|---|---|---|
| Cursor too slow / too fast | `h_gain`, `v_gain` | up / down |
| Cursor shimmers at rest | `min_cutoff` | down (calmer, more lag) |
| Fast movement feels delayed | `beta` | up |
| Marker lost in a bright room | `exposure` | down to -10 |
| Something else gets tracked | `threshold` | up toward 255 |
| Cursor jumps to a bright object | `max_area` | down |

Shorter exposure improves precision as well as contrast: the sub-pixel centroid
needs a brightness gradient across the blob, and a saturated marker is a flat
plateau. Prefer the shortest exposure that still holds the dot.

## Known gotchas

**F9 is claimed globally while AccessCam runs.** Nothing else on the system
receives it. If another application needs F9, change `hotkey` in the config —
any function key works unmodified, and chords like `ctrl+alt+p` are accepted
too.

**A rival low-level keyboard hook will silently eat the hotkey.** SmartNav's
software claims F9 that way. The registration still succeeds, so the only
symptom is a hotkey that never fires. If that happens, remap the other
application or pick a different key.

**Injected keystrokes do not trigger the hotkey.** Any script that tries to
test it with `SendInput` will report failure regardless. Only a real press
counts.

**The camera must be on the machine running AccessCam.** If a monitor is shared
between machines through a switch, the USB connection has to follow.
