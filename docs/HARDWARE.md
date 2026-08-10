# Hardware Notes

## Camera: Arducam 1080P Day & Night Vision USB (Amazon B0829HZ3Q7, module B0205)

| Spec | Value | Relevance |
|---|---|---|
| Sensor | 1/2.7" OV2710 CMOS | IR-sensitive with the IR-cut filter out of the path |
| Frame rates | MJPEG: 30fps at every resolution (640×480 → 1920×1080); YUY2 much slower | **Use MJPEG.** 640×480@30 is the sweet spot: full fps, least USB2 bandwidth/latency |
| Illumination | 6× 850nm IR LEDs | Lights up the retroreflective dot; driven by the same photoresistor circuit as the IR-cut switch |
| IR-cut filter | Mechanical, auto-switched by an onboard **photoresistor** | ⚠️ See below — must be forced to night mode |
| Lens | 105° F1.6 "starlight" | Wide FOV means fewer pixels per degree of head motion; crop/ROI in software if needed |
| Interface | USB 2.0 UVC | Driverless on Windows/Linux/macOS |

## ⚠️ Critical: force night mode

The board's photoresistor senses **ambient visible light**. In a normally lit
room the camera sits in *day* mode: the IR-cut filter blocks 850nm and the IR
LEDs are off — retroreflective tracking is impossible.

**The 3D-printed housing must cover the photoresistor** (a small light-tight
shroud or a blob of the enclosure over it) so the board always believes it is
dark: filter stays out of the light path, IR LEDs stay on. Verify before
finalizing the print: cover the photoresistor with a fingertip/tape and
confirm the LEDs glow faintly red and the image goes IR (room lights on).

## Housing / monitor mount — SolidWorks design requirements

1. **Photoresistor shroud** — light-tight cover over the photoresistor only;
   do not block the lens or the six IR LEDs.
2. **Monitor-top mount** — SmartNav-style perch: rests on the top bezel with a
   rear counterweight/clamp lip; fits bezels ~10–40mm deep.
3. **Tilt adjustment** — ±20° pitch so the camera can aim at the user's
   forehead from above the screen; friction hinge or notched detents.
4. **Filter slot (optional but recommended)** — a slot in front of the lens
   for an 850nm IR-pass filter (a cheap acrylic square, or the classic exposed
   film / floppy-disk-magnetic-media stopgap). Blocks visible light so the dot
   is nearly the only thing in frame.
5. **Ventilation + strain relief** — small vents; route the USB pigtail so it
   doesn't torque the board.
6. **Board mounting** — the module is a bare 38×38mm-class PCB (measure the
   actual board and hole spacing with calipers before modeling); standoffs for
   M2 screws or snap posts.

## Mount base provenance — why `MonitorMountBase` is in inches

The original plan was to reuse the SmartNav's own monitor base. That was
dropped: **the SmartNav stays connected and working** as a fallback while
AccessCam is built (see the "user's daily driver breaks" risk in
PROJECT_PLAN.md), so its base can't be cannibalised.

`MonitorMountBase` is therefore a replica, traced from the only reference
available — the original base's STL, which was authored in inches. The part is
consequently modelled in **inches** (2.000 × 1.550 × 1.400in = 50.80 × 39.37 ×
35.56mm, 0.150in walls) while every other part in `hardware/` is metric.

**This is intentional, not a units bug.** The geometry is physically correct
and its STEP declares `CONVERSION_BASED_UNIT('INCH')`, so FreeCAD/Fusion place
it at the right size. Don't "fix" it by rescaling — that would break the fit
against the real monitor. The production housing (M3) rebuilds this in MMGS.

## Development prototype vs. production housing

The current `CameraHousing` / `HousingBottom` / `MonitorMountBase` set is a
**bring-up prototype**, not the shipping design. The camera slots in from above
and is held by gravity — no fasteners, no captive retention, no tilt detents,
and no fastened joint between the housing and the mount base. That is a
deliberate trade: it gets a camera pointed at the user quickly and lets the
board be pulled out freely while exposure, filtering, and aim are still being
tuned. Requirements 2, 3 and 6 above are only partly met by it.

Do not print this for daily use. The production revision is scheduled as the
hardware track of **M3**, once development testing has settled the geometry.

## Windows capture backend

OpenCV offers two Windows backends and they do not behave the same. Measured
on a test camera (2026-08-08, OpenCV 5.0):

| Backend | Exposure control | Notes |
|---|---|---|
| `CAP_DSHOW` (DirectShow) | Full range — accepted −10 | Currently the default on Windows |
| `CAP_MSMF` (Media Foundation) | **Clamped** — requested −10, held at −6 | Also reports no usable FOURCC |

Short exposure is what makes the marker the only bright object in a lit room,
so a backend that clamps the range can make tracking impossible. The bring-up
tool displays both the requested and driver-reported exposure so clamping is
visible, and `--backend dshow|msmf` switches between them. Re-check this on
the Arducam — the behaviour is driver-specific, not universal.

### Confirmed on the Arducam (2026-08-09, OpenCV 5.0, Python 3.14)

The clamping above reproduces exactly: **MSMF holds at −6, DirectShow grants
−10.** So DirectShow stays the Windows default.

The Arducam enumerates as a generic **"USB Camera"** (`VID_0C45&PID_6366`).
With a second webcam attached it came up as **index 1**, so bring-up needs
`--device 1`; it is the only index granting 1920×1080, which is how to tell it
apart from a LifeCam-class device.

**FOURCC ordering gotcha — costs 2× the frame rate.** Setting `CAP_PROP_FOURCC`
*before* the frame size leaves this camera in uncompressed YUY2. Setting it
only *after* the size negotiates MJPEG. Setting it both before and after fails
the same way as before-only, so the first call is what poisons the negotiation:

| DirectShow call order | 640×480 | 1280×720 |
|---|---|---|
| FOURCC before size | YUY2, 14.8fps | YUY2, 10.0fps |
| **FOURCC after size** | **MJPG, 29.3fps** | **MJPG, 29.3fps** |
| FOURCC before *and* after | YUY2, 14.8fps | YUY2, 10.0fps |

`camera.py` sets it after the size for this reason. Exposure −10 is honoured in
every one of those orderings, so this is purely about frame rate.

MSMF reaches 30fps at 640×480 and even 1920×1080, which means it negotiates
MJPEG on its own — it just never reports a readable FOURCC. It remains
unusable here because of the −6 exposure clamp.

## Retroreflective marker

- Material: **3M Scotchlite 7610** high-gain reflective tape (this is what
  SmartNav dots were). eBay/Amazon sell small sheets cheaply.
- Punch 8–12mm dots with a hole punch. Backing: adhesive on forehead sticker,
  glasses frame, or hat brim — same spots SmartNav users already use.
- Spare SmartNav dots also work as-is.

## Validation checklist (before M1 exit)

- [ ] Camera enumerates as UVC on Windows; MJPEG 640×480@30 confirmed with a
      real fps counter (not the advertised number)
- [ ] Photoresistor shrouded → IR LEDs on and filter open with room lights on
- [ ] Exposure can be driven low enough (via OpenCV `CAP_PROP_EXPOSURE`) that
      the dot is the brightest blob in frame in a daylight room
- [ ] Dot tracked across the full comfortable head-motion range at seating
      distance; note the pixel span (this calibrates default gains)
- [ ] Jitter while holding still measured (pixel std-dev) — feeds smoothing
      defaults
