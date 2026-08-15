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

## 5. Run it as administrator

Not optional if you use an on-screen keyboard, or anything else that reacts to
the pointer hovering.

Windows' UIPI stops a normal-privilege process delivering input to a
higher-privilege one. The cursor still moves — the cursor is global — but the
target window never receives the mouse messages, so **hover-driven UI silently
stops responding**. Confirmed against Comfort On-Screen Keyboard Pro: keys do
not highlight under AccessCam unelevated, and highlight immediately when it is
launched from an Administrator terminal. UAC prompts and applications running
as administrator behave the same way.

AccessCam prints a note at startup when it is not elevated, so this is visible
rather than a mystery.

Open PowerShell **as Administrator**, then:

```powershell
cd <wherever you cloned it>
.venv\Scripts\accesscam.exe
```

To skip the elevation prompt every time, register it as a scheduled task that
runs with highest privileges at logon:

```powershell
schtasks /create /tn AccessCam /rl highest /sc onlogon /f `
  /tr "<path>\.venv\Scripts\accesscam.exe"
```

## 6. First light

```powershell
python -m accesscam
```

It **starts paused**. Press **F9** to take control, F9 again to park the
cursor. Ctrl+C in the terminal quits.

Expect to want a different gain immediately. Edit `h_gain` and `v_gain` in the
config: higher means the cursor travels further for the same head movement.
The defaults of 31 and 32 are calibrated for one 2560x1440 screen.

## A known-good starting point

The config lives in `%APPDATA%\AccessCam\config.json` and is **not** in the
repository, so it does not travel with a clone. These are the values tuned on
the development machine on 2026-08-10, against an Arducam on a monitor-top
mount at normal seating distance:

```json
{
  "device": 1,
  "exposure": -9,
  "threshold": 200,
  "h_gain": 100.0,
  "v_gain": 70.0,
  "min_cutoff": 0.15,
  "beta": 0.4,
  "max_step": 2500.0,
  "hotkey": "f9"
}
```

Anything omitted falls back to its default, so this is a complete file as it
stands. Two caveats when copying it to another machine:

- **`device` will differ.** Run `--list-devices` first.
- **The gains depend on how far the camera sits from your head**, since they
  are calibrated against how far the marker travels across the sensor. If the
  mount geometry is the same, they should carry over; if the cursor feels wrong
  in the first minute, gain is the thing to change.
- **No region of interest is set here**, so the whole frame is searched. If a
  bright window competes with the marker in your room, add one — and expect to
  revisit the gains afterwards, since a box changes how much of the frame your
  head crosses.

`v_gain` being lower than `h_gain` is deliberate — vertical head movement has
less comfortable range than horizontal, so it needs less amplification per
pixel to cover its axis.

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
| Want to re-bias your head at an edge | `clutch` | up from 0, try 600 |
| Cursor shimmers at rest | `min_cutoff` | down (calmer, more lag) |
| Fast movement feels delayed | `beta` | up |
| Marker lost in a bright room | `exposure` | down to -10 |
| Something else gets tracked | `threshold` | up toward 255 |
| Cursor jumps to a bright object | `max_area` | down |
| A daylit window keeps stealing it | `roi_*` | draw a box around yourself |

Shorter exposure improves precision as well as contrast: the sub-pixel centroid
needs a brightness gradient across the blob, and a saturated marker is a flat
plateau. Prefer the shortest exposure that still holds the dot.

## When something bright keeps stealing the track

A window in daylight images as bright as the marker, and neither the shape nor
the brightness filter can reject it — a window is neither dim nor elongated. No
exposure or threshold will separate them either, because the offender is as
bright as the thing you are looking for.

Exclude it by area instead. Only blobs whose centre falls inside the region of
interest are considered, so a box drawn around yourself removes anything at the
frame edges:

```json
{
  "roi_x": 257,
  "roi_y": 237,
  "roi_w": 268,
  "roi_h": 233
}
```

All four at `0` — the default — searches the whole frame. `roi_w` or `roi_h` of
`0` counts as disabled rather than as a box that rejects everything.

Two things to know before relying on it. The box is fixed **in the camera
frame**, not to you: move your chair and you can leave it, and tracking then
stops entirely rather than degrading. That is a worse failure than a stolen
track, which is why it is off unless you ask for it. And the box shrinks how
much of the frame your head crosses, so gains tuned before setting one will
feel faster afterwards.

Pick the box visually rather than guessing pixels — see below.

## Tuning against the live preview

`tools/camera_bringup.py` is the M1 bring-up tool, and it stays useful long
after bring-up: it shows the camera with the tracked blob outlined, so you can
watch what the tracker is actually choosing while you change settings. It never
touches the cursor.

```powershell
.venv\Scripts\python.exe tools\camera_bringup.py --device 1
```

The HUD reports fps, exposure, threshold, the marker's position, area and
brightness — or `dot NOT FOUND` — plus travel range and the current box.

| Key | Effect |
|---|---|
| drag | draw a region of interest; outside it dims |
| `c` | clear the region of interest |
| `w` | write exposure, threshold and the box to the config |
| `[` / `]` | lower / raise `threshold` |
| `-` / `=` | shorten / lengthen `exposure` |
| `j` | measure jitter — hold still for a couple of seconds |
| `r` | reset the travel-range measurement |
| `s` | save a snapshot to `bringup/` |
| `a` | toggle auto exposure, for comparison only |
| `q` | quit and print a summary |

`w` loads the existing config before writing, so gains, smoothing and
everything else it does not tune survive untouched. Note the keys go to the
preview window, not the terminal — click it first.

Travel range is worth watching while you are in here: it accumulates only while
the marker is found, so a figure that stays near zero means the track is sitting
on something stationary rather than on you.

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
