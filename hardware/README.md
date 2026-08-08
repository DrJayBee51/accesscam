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

See [../docs/HARDWARE.md](../docs/HARDWARE.md) for the design requirements the
housing must satisfy (photoresistor shroud, filter slot, aiming adjustment).
