"""Entry point: `python -m accesscam` or the `accesscam` console script."""

import sys

from accesscam.app import main

if __name__ == "__main__":
    sys.exit(main())
