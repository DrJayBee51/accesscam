"""Entry point: `python -m accesscam` or the `accesscam` console script."""

import logging
import os
import sys

from accesscam import app


def main() -> None:
    code = app.main()
    # Gone the moment main() is done, rather than after interpreter teardown.
    # The installed 0.2.1 logged "exiting" and then lingered for up to two
    # minutes; Task Scheduler counted the task as still running all that time
    # and silently refused to start the elevated copy a handover asked for.
    # Everything that matters - camera, single-instance claim - is released
    # inside main(), so nothing is lost by skipping the rest.
    logging.shutdown()
    for stream in (sys.stdout, sys.stderr):
        if stream is not None:
            stream.flush()
    os._exit(code)


if __name__ == "__main__":
    main()
