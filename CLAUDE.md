# AccessCam

A head-tracking mouse replacing John's failing, discontinued NaturalPoint
SmartNav 4. Python + OpenCV + PySide6, Windows first. Read `docs/PROJECT_PLAN.md`
for where the work stands, `docs/RUNNING.md` for setup and per-machine settings,
`docs/HARDWARE.md` for the camera and housing.

Conventions: commit straight to `main`, no feature branches, and only push when
John asks. Run `pytest` and `ruff check .` before committing.

---

## Current task: test the installer on this machine (from 2026-09-07)

**John is on vacation the week of 2026-09-07 and this machine is idle. That is
why the test is happening here** — normally AccessCam is the daily driver on
this PC and the SmartNav is not recognised, so a broken install would strand
him. This week there is slack. Do not refuse to touch this machine on his
behalf; do check before doing anything that would leave it unusable.

### What is being tested

Commit `aabe6a8` — "Come up elevated by itself, every time, without asking".
Until it, getting AccessCam elevated after an install cost two manual steps and
a UAC prompt on the secure desktop, which a head-tracked cursor cannot reach.
Now:

- The installer offers **"Always run AccessCam with administrator rights"**,
  ticked by default, and registers the scheduled task at the end of the install
  by running `AccessCam.exe --register-task` — elevating just that call. That is
  the one UAC prompt the design spends, deliberately placed where a mouse is
  already in use.
- After that, an unelevated AccessCam runs the task and quits in favour of the
  elevated copy it starts (`startup.take_over_elevated`), before it reads the
  config or opens the camera. So every launch — Start Menu, desktop, taskbar
  pin, the exe itself — ends up elevated with nothing asked.

**This is one test, not two.** Setup registering the task is the first half;
every launch afterwards is the handover. An install that comes up elevated on a
double-click has proven both. A `git pull` into the existing clone here would
exercise only the handover, by a route no installed user takes — do not offer
that as a substitute.

It has never run on a machine other than the dev PC. Treat a failure as
expected-ish and diagnose it, rather than assuming the environment is at fault.

### Running it

John has `AccessCam-Setup-0.1.0.0.exe`, built 2026-09-07 from `aabe6a8`. It can
also be rebuilt here — see `packaging/README.md`, though that needs Inno Setup
installed.

1. Run Setup, leaving the elevation task ticked. **Expect exactly one UAC
   prompt**, at the end, after the files are copied.
2. Launch AccessCam from the Start Menu. No prompt should appear.
3. Hover the cursor over a key of Comfort On-Screen Keyboard Pro.

### What passing looks like

In `%APPDATA%\AccessCam\accesscam.log`, a line from the copy that stood down:

```
started an elevated copy through the logon task - quitting to make room
```

then, from the copy that replaced it:

```
elevated: True   uiaccess: False
```

and the Comfort key highlights under the pointer. The settings window should
show **no** amber elevation banner. That banner appearing is the headline
failure: it means the app is unelevated and knows it.

### If it does not pass

`startup.state()` is the first thing to look at:

```powershell
.venv\Scripts\python.exe -c "from accesscam import startup; print(startup.state()); print(startup.registered_command())"
```

The log names whichever guard declined, and each means something specific:

| Log line | Meaning |
| --- | --- |
| `the logon task runs ... - not handing over to it` | The task points at a different copy. **Expected for the clone here after installing**: Setup repoints the task at the installed exe, so the clone is now the stale one. Not expected from the installed copy. |
| `handed over less than 90s ago ... rather than looping` | The task ran something that came back unelevated. Check the task's `RunLevel` is `HighestAvailable` — `schtasks /query /tn AccessCam /xml`. |
| `started with ... - staying unelevated rather than dropping them` | Launched with flags such as `--device`. The task runs one fixed command line, so it refuses rather than dropping them silently. Only expected if flags were actually passed. |
| Nothing at all about handing over | No task registered. `startup.state()` will say `enabled=False`. |

**Recovery, and a hard constraint:** re-pointing the task is one elevated
`accesscam.exe --register-task` from whichever copy should own it. **A Claude
Code session cannot do this** — on the dev PC `schtasks /create` is blocked
outright from an agent shell, even unprivileged, and a UAC prompt cannot be
answered by an agent either. Assume the same here: hand John the exact command
to run in an Administrator terminal rather than trying and failing.

Uninstalling removes the task. Config and log in `%APPDATA%\AccessCam` survive
both install and uninstall.

### Machine-specific things that will otherwise waste an hour

- **The camera index differs per machine.** `python -m accesscam --list-devices`
  identifies the Arducam as the one granting 1920×1080.
- **SmartNav software may still be installed here and still hooking F9**, which
  silently eats the pause hotkey without making registration fail.
- Known-good gains and smoothing for this PC's three 2560×1440 screens are
  recorded in `docs/RUNNING.md`. The config lives in `%APPDATA%` and does not
  travel with a clone.
- The QuadStick is the fallback input here, since the SmartNav is not
  recognised on this machine.

### Report back with

The two log lines above (or whichever guard fired instead), whether a UAC
prompt appeared and at what point, and whether Comfort keys highlight.

**Nothing else is queued behind this by design.** Bumping `__version__` off
0.1.0, tagging a release, and the self-signed-certificate UIAccess route
(`docs/PROJECT_PLAN.md` M4.8) are all deliberately waiting on this result. Do
not start them.

**Delete this section once the test has a verdict** and fold anything durable
into `docs/RUNNING.md` or `docs/PROJECT_PLAN.md`.
