"""PySide6 front end.

Imported lazily by `app.main`, so the headless path never pays for Qt and a
missing PySide6 install cannot stop the cursor working.
"""

from __future__ import annotations

__all__ = ["launch"]


def launch(*args, **kwargs) -> int:
    """Start the settings window. Imports Qt only when actually called."""
    from accesscam.ui.main_window import launch as _launch

    return _launch(*args, **kwargs)
