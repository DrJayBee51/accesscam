# Artwork

Drop files in here and AccessCam uses them. Nothing needs rebuilding or
registering: the loader looks for these names at startup and falls back to the
drawn ring-and-dot when a file is missing or unreadable, so half-finished
artwork is a safe state to leave the repository in.

| File | Where it appears | Notes |
|---|---|---|
| `accesscam.ico` | Desktop, Start menu, taskbar, Alt-Tab, the window's title bar, the installer | Multi-size `.ico` |
| `tray-active.png` | Notification area, **while the cursor is being driven** | Square PNG, transparent |
| `tray-paused.png` | Notification area, **while the cursor is parked** | Square PNG, transparent |
| `tray-trouble.png` | Notification area, **while something is wrong** | Square PNG, transparent |

## The three states

The design these were specified against: a head-and-shoulders silhouette, with
the marker on the face.

| State | What it means | The idea |
|---|---|---|
| Active | AccessCam has the pointer and can see you | Silhouette **with** the marker |
| Parked | Running, but not driving the cursor — F9 to take it | Silhouette **without** the marker |
| Trouble | Running, but something is stopping it working — a dead camera, or a hotkey that would not register | Silhouette with a **red X** |

The three differ in *what is drawn*, not only in colour, which is the point —
see below.

**What counts as trouble**, decided in `src/accesscam/health.py`:

- **No frames from the camera** for 3 seconds. Unplugged, driver fallen over,
  or another application has taken it.
- **The pause hotkey would not register**, which is permanent for the session
  and means the cursor cannot be parked from the keyboard.

**A missing marker is not trouble**, and that is worth stating because it looks
like the obvious candidate. Losing it is ordinary: you leave the desk to eat and
come back to a tracker that picks up where it left off, exactly as the SmartNav
does. AccessCam does nothing when the marker goes - the cursor stops where it
is, and the first frame after reacquisition is deliberately a zero movement so
it cannot jump - so there is nothing to report. Flagging it would have painted
the tray red through every lunch break. The window says whether the marker is
currently visible, and the tray tooltip mentions it, for anyone actually asking.

Slow to complain and quick to forgive: a condition has to persist before it is
shown, and clears the instant it goes away. An indicator that cries wolf gets
ignored on the one occasion it is right. The tooltip carries which of the three
it is and what to do about it.

## What the tray icon has to do

It is not decoration. Once the window is hidden the tray icon is the only thing
saying whether AccessCam currently has the pointer, and "is this thing on" is
the question a head-tracking mouse raises most often. So the two states have to
be **distinguishable at 16 pixels, at a glance, without moving the cursor over
it** — reading a tooltip requires the pointer, which is exactly what is in
question when the answer matters.

Three constraints worth designing against rather than discovering:

1. **16px is the real size.** Windows shows the notification area at 16px at
   100% scaling, 20–24px at higher. A 2px line is one pixel after rounding, and
   fine detail turns to grey mush. Draw it at 16 and scale *up*, not the other
   way round.
2. **It sits on both a dark and a light taskbar**, depending on the user's
   Windows theme, and you cannot detect which from a static file. The current
   drawn glyph fails this: its near-white ring nearly vanishes on a light
   taskbar. A shape that reads on both — or a dark outline around a light
   shape — survives either.
3. **Do not carry the state on colour alone.** Green against red is the least
   legible pair for the commonest form of colour blindness, and this is an
   accessibility tool. The marker present / absent / struck through does the
   work by itself, and colour reinforces it — which is why the specified design
   works: printed in greyscale, the three are still three.

## Sizes

`accesscam.ico` should contain 16, 24, 32, 48, 64, 128 and 256px images, each
drawn rather than downsampled, for the same reason as above. If your tool only
exports one size, export a 256px PNG and say so — converting it is a minute's
work and better done once, here, than by every viewer.

Tray PNGs: 32px or 64px square is plenty. Qt scales them down for the tray.

## Editable sources

Keep the working file (`.xcf`, `.psd`, whatever the tool produces) alongside
its exported `.png`, the same way `hardware/` keeps a `.SLDPRT` beside its
STL and STEP. Someone tweaking one state later should not have to redraw the
other two from scratch to match.

## The fallback

`tools/make_icon.py` regenerates `accesscam.ico` from the glyph drawn in
`src/accesscam/ui/tray.py`. **Do not run it once real artwork is in place** — it
overwrites the file. It exists so a checkout without artwork still has an icon
of its own rather than a generic interpreter icon.
