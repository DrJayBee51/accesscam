# Hardware

CAD files for the camera housing and monitor mount, organized **one folder per
part**:

```
hardware/
  camera-housing/
    camera-housing.sldprt   (SolidWorks source)
    camera-housing.stl      (print-ready mesh)
    camera-housing.step     (neutral format for FreeCAD/Fusion users)
  monitor-clamp/
    ...
```

## Rules

Every part folder **must** contain all three of:

1. a SolidWorks source file (`.sldprt` or `.sldasm`)
2. an `.stl` export (ready to slice)
3. a `.step` export (so contributors without SolidWorks can modify the design)

CI enforces this: `python tools/check_hardware.py` runs on every push and
fails if any part folder is incomplete. Run it locally before committing.

Name the files after the folder. When you change a part, re-export **both**
the STL and STEP so they never drift out of sync with the SolidWorks source.

## Export settings

**STEP: use AP214** (or AP242 if your SolidWorks version offers it — it's the
modern standard that merged AP203 and AP214, and FreeCAD 0.19+ and Fusion both
read it). AP214 preserves colors, materials, and assembly structure, which
plain AP203 does not. Set this once in Tools → Options → Export → STEP.

**STL: binary format, and keep the triangle count sane.** Deviation/angle
tolerance drives file size hard — a very fine export of a simple part can
produce 700k triangles and a 35 MB file. Git stores every revision of a binary
forever, so oversized meshes bloat the repo permanently. Aim for a few MB at
most; use the finest setting only for parts whose printed surface finish
actually depends on it (never for fit-check mockups).

See [../docs/HARDWARE.md](../docs/HARDWARE.md) for the design requirements the
housing must satisfy (photoresistor shroud, filter slot, aiming adjustment).
