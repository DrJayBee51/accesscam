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
3. **Do not carry the state on colour alone.** Green-driving and red-parked is
   the least legible pair for the commonest form of colour blindness, and this
   is an accessibility tool. Change the *shape* too: filled against hollow, or
   present against struck through. Colour can carry it as well; it should not
   carry it by itself.

## Sizes

`accesscam.ico` should contain 16, 24, 32, 48, 64, 128 and 256px images, each
drawn rather than downsampled, for the same reason as above. If your tool only
exports one size, export a 256px PNG and say so — converting it is a minute's
work and better done once, here, than by every viewer.

Tray PNGs: 32px or 64px square is plenty. Qt scales them down for the tray.

## The fallback

`tools/make_icon.py` regenerates `accesscam.ico` from the glyph drawn in
`src/accesscam/ui/tray.py`. **Do not run it once real artwork is in place** — it
overwrites the file. It exists so a checkout without artwork still has an icon
of its own rather than a generic interpreter icon.
