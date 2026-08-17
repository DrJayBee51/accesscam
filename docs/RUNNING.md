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

### Starting it elevated on demand, without a UAC prompt

The task is not only for logon. `schtasks /run /tn AccessCam` starts it
elevated at any time and asks nobody — creating the task needed administrator
rights once; running it never does.

That matters more here than convenience. A process cannot elevate itself once
it is running, so every other route to administrator goes through a UAC prompt
on the secure desktop — which a head-tracked cursor cannot reach, because
AccessCam is not elevated at that moment by definition. Anyone who needs this
application to move their pointer would be stranded at a dialog they cannot
click. The scheduled task is the only route that never asks.

`tools/launch-elevated.vbs` is that one line, plus a message box if the task is
missing rather than a silent no-op. Make a shortcut to it:

```powershell
$repo = "<path to the repo>"
$shell = New-Object -ComObject WScript.Shell
$lnk = $shell.CreateShortcut([IO.Path]::Combine(
    [Environment]::GetFolderPath('Programs'), 'AccessCam.lnk'))
$lnk.TargetPath = "$env:SystemRoot\System32\wscript.exe"
$lnk.Arguments = "`"$repo\tools\launch-elevated.vbs`""
$lnk.IconLocation = "$repo\assets\accesscam.ico,0"
$lnk.Save()
```

Then pin it to the taskbar or the Start menu. `wscript` rather than a shortcut
straight to `schtasks.exe` only so that no console window flashes up.

If Windows Script Host is disabled by policy — plausible on a managed work
machine — point the shortcut at `schtasks.exe` with arguments
`/run /tn AccessCam` instead and accept the flash.

`assets/accesscam.ico` is generated from the same glyph the tray draws, so the
two cannot drift apart: `python tools/make_icon.py assets/accesscam.ico`.

## If the camera number is wrong

With `--ui`, AccessCam does not give up when it cannot open the camera in the
config: it scans for what is connected and offers the list, with the IR camera
marked as the one granting 1920×1080. Choose it and the answer is saved, so the
dialog appears once. The list is fully keyboard-operable — arrows and Enter —
since anyone meeting it does not have a working pointer yet.

Headless (`python -m accesscam` with no `--ui`) still exits, deliberately:
there is a console right there, and `--list-devices` answers the same question
without a window.

## 6. First light

```powershell
python -m accesscam
```

It **starts paused**. Press **F9** to take control, F9 again to park the
cursor. Ctrl+C in the terminal quits.

Expect to want a different gain immediately. Edit `h_gain` and `v_gain` in the
config: higher means the cursor travels further for the same head movement.
The defaults of 31 and 32 are calibrated for one 2560x1440 screen.

## Known-good settings, per machine

The config lives in `%APPDATA%\AccessCam\config.json` and is **not** in the
repository, so it does not travel with a clone. Recorded here instead, one block
per machine, because the two installations have diverged enough that a single
"starting point" is now misleading: they differ in screen count, in room
lighting, and therefore in gain.

There is deliberately no profile feature to switch between these. `%APPDATA%` is
already per-machine, so each installation keeps its own settings without help;
what this section solves is carrying them between machines through the
repository, which is a development concern rather than something a user of an
installed app ever meets. Named profiles are an M5 item for shared institutional
machines — see PROJECT_PLAN.md.

### Development PC — four screens, 7680×3600

Tuned 2026-08-10, retuned 2026-08-15 when pointer acceleration landed:

```json
{
  "device": 1,
  "exposure": -9,
  "threshold": 200,
  "h_gain": 120.0,
  "v_gain": 90.0,
  "min_cutoff": 0.15,
  "beta": 0.4,
  "max_step": 2500.0,
  "accel_floor": 0.35,
  "accel_knee": 25.0,
  "accel_sharpness": 3.0,
  "hotkey": "f9"
}
```

The gains went **up** — 100→120 and 70→90 — in the same change that added the
curve, and that is the point rather than a coincidence: damping the gain at rest
bought enough precision to afford a faster pointer everywhere else. Tuning them
apart from the curve would have found neither.

No region of interest is set here; the whole frame is searched.

### Work PC — three screens, 2560×1440 each

The daily driver, and where four days of full-day use surfaced the jitter
problem the curve fixes. A region of interest is set here because a daylit
office window rivalled the marker.

Verbatim from that machine's `config.json` on 2026-08-16, after its first
tuning session on the M3 build:

```json
{
  "accel_floor": 0.4,
  "accel_knee": 25.0,
  "accel_sharpness": 3.5,
  "backend": "dshow",
  "beta": 0.3,
  "clutch": 0.0,
  "d_cutoff": 1.0,
  "dead_zone": 0.0,
  "device": 1,
  "exposure": -9,
  "fps": 30,
  "h_gain": 105.0,
  "height": 480,
  "hotkey": "f9",
  "invert_x": true,
  "invert_y": false,
  "max_area": 5000.0,
  "max_jump": 120.0,
  "max_step": 2500.0,
  "min_area": 4.0,
  "min_circularity": 0.5,
  "min_cutoff": 0.3,
  "roi_h": 233,
  "roi_w": 268,
  "roi_x": 257,
  "roi_y": 237,
  "start_minimized": false,
  "threshold": 200,
  "v_gain": 80.0,
  "width": 640
}
```

**The curve bought room for faster gains here too.** 85/60 before it, 105/80
after — the same trade the development PC made, on a different screen count and
a different mount distance, which is the open question from the M2 notes
answered. The floor settled slightly higher (0.4 against 0.35) and the knee
matches at 25.

`min_cutoff` is 0.3 rather than the development PC's 0.15. Slow movement is
where the difference shows: below about 0.3 the resting jitter stops improving
while lag keeps growing, and on this machine that lag was noticeable when
placing the pointer on an on-screen keyboard key.

### Notes that apply to both

Anything omitted falls back to its default, so each block above is a complete
file as it stands.

- **`device` will differ.** Run `--list-devices` on each machine.
- **The gains depend on how far the camera sits from your head**, since they are
  calibrated against how far the marker travels across the sensor. If the mount
  geometry matches they should carry over; if the cursor feels wrong in the
  first minute, gain is the thing to change.
- **A region of interest changes the gains.** The box shrinks how much of the
  frame your head crosses, so gains tuned before setting one feel faster after.
- **`v_gain` lower than `h_gain` is deliberate** — vertical head movement has
  less comfortable range than horizontal, so it needs less amplification per
  pixel to cover its axis.

## The settings window

```powershell
.venv\Scripts\accesscam.exe --ui
```

Two tabs. **Camera & Marker** is everything that changes what the tracker sees —
exposure, threshold, the blob filters, and the region searched, which is set by
dragging the corner handles on the preview. **Cursor Movement** is everything
downstream of finding the dot — the gains, the acceleration curve, smoothing and
the clutch. Every change applies to the live cursor immediately; nothing needs a
restart to be felt.

Each setting has a `?` beside it. They open on click rather than on hover,
because a head-tracked pointer never stops moving and a hover tooltip would
disappear before it could be read.

Nothing in the window needs a drag. Every value has step buttons worth one click
each and steps with the arrow keys once focused; the slider is there for when
the pointer is cooperating. The one exception is the region box, and its
handles have a grab radius considerably larger than they are drawn.

**It lives in the tray.** The icon is green while the cursor is being driven and
red while it is parked, so the state is visible with the window closed. Closing
the window hides it there rather than quitting — ending cursor control with a
stray click on a title bar is a worse outcome than a window you have to reopen.
Quit is in the tray menu, along with **Start minimised**, which opens straight
to the tray on the next run.

Settings are not saved until you press **Save settings**. **Revert to saved**
puts back whatever is in the file, which is the way out of a session of tuning
that went nowhere.

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
| Cannot hold still to select text | `accel_floor` | down from 1.0, try 0.35 |
| Long sweeps feel sluggish | `accel_knee` | down from 40 |

Shorter exposure improves precision as well as contrast: the sub-pixel centroid
needs a brightness gradient across the blob, and a saturated marker is a flat
plateau. Prefer the shortest exposure that still holds the dot.

## Holding the cursor still (pointer acceleration)

Four days of full-day use at work surfaced one problem the smoother cannot fix:
about 4px of wander remains at rest, and a flat gain multiplies all of it. That
is tiring over hours and it makes selecting text hard, because a caret has to be
placed precisely and then held.

`accel_floor` scales the gain down while the marker is nearly still and restores
it as you move, so precision and reach stop competing for one number:

```json
{
  "accel_floor": 0.35,
  "accel_knee": 40.0,
  "accel_sharpness": 1.8
}
```

- **`accel_floor`** — fraction of full gain used at rest. `1.0` is the default
  and disables the curve entirely, so the mapper behaves exactly as it did
  before. `0.35` cuts the resting wander to roughly a third.
- **`accel_knee`** — marker speed, in camera px/s, at which the gain has climbed
  halfway back. Below it you are positioning; above it you are travelling.
- **`accel_sharpness`** — how abruptly the gain climbs through the knee. Most
  setups never need to move it.

The scale is taken from the speed of the whole 2D movement and applied to
`h_gain` and `v_gain` together, so your existing calibration keeps its ratio and
a diagonal is never bent. The curve only ever reduces gain, so a fast sweep still
reaches as far as it does today.

Tune it in this order — each step depends on the one before:

1. **Move `accel_floor` alone** until you can place and hold a caret. This is
   the parameter that fixes the fatigue.
2. **Then check a long sweep** across every screen. If it drags, lower
   `accel_knee` — you are still in the slow region during real travel.
3. **Only then touch `accel_sharpness`**, up if the transition feels mushy, down
   if the cursor lurches as it picks up speed.

Give any setting a full working day before judging it. This was found over four
days, not four minutes, and a curve that feels strange for ten minutes is often
the right one.

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

## When it does not start at logon

Read the log first. It is at:

```
%APPDATA%\AccessCam\accesscam.log
```

Every run appends to it, and this is the only place a logon start can speak
from: registered against `pythonw` there is no console, `print` goes nowhere,
and an unhandled exception disappears with the process. A healthy start looks
like this, and stops at whichever line it could not get past:

```
--- starting: --ui --wait-for-camera 60
elevated: True
creating the cursor backend
Qt is up
camera 1 opened on attempt 4 after 3.2s
window built
tray icon shown
pause hotkey 'f9' registered
running
```

`camera 1 opened on attempt 4` is worth watching. Attempt 1 means the camera
was ready before AccessCam asked; a high number means the USB enumeration race
is real on this machine and `--wait-for-camera` is what is covering it.

**`LastTaskResult` tells you whether the task even fired**, which separates a
scheduling problem from an application one in one command:

```powershell
Get-ScheduledTaskInfo -TaskName AccessCam
```

A `LastRunTime` matching the logon with `LastTaskResult = 1` means the trigger
worked and the app died — go to the log. Note that 1 is Python's exit code for
*any* unhandled exception, so it names nothing on its own.

The Task Scheduler's own Operational log is disabled by default and is worth
turning on before chasing a scheduling problem (Administrator):

```powershell
wevtutil sl Microsoft-Windows-TaskScheduler/Operational /e:true
```

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

**At logon, AccessCam can start before the desktop is finished.** The trigger
fires within a second of the logon notification, and at that moment the camera
may still be enumerating and Explorer may not have created the notification
area yet. Both are waited for, for `--wait-for-camera` seconds, rather than
being asked about once — which is why the tray icon sometimes appears a few
seconds after the desktop rather than with it.
