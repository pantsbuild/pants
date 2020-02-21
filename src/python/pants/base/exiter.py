# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import logging
import sys
import traceback
from typing import Callable, Union

from pants.util.strutil import ensure_binary

logger = logging.getLogger(__name__)


# Centralize integer return codes for the pants process. We just use a single bit for now.
# TODO: make these into an enum!
PANTS_SUCCEEDED_EXIT_CODE = 0
PANTS_FAILED_EXIT_CODE = 1

ExitCode = int


class Exiter:
    """A class that provides standard runtime exit behavior.

    `pants.base.exception_sink.ExceptionSink` handles exceptions and fatal signals, delegating to an
    Exiter instance which can be set process-globally with ExceptionSink.reset_exiter(). Call
    .exit() or .exit_and_fail() on an Exiter instance when you wish to exit the runtime.
    """

    def __init__(self, exiter: Callable[[Union[ExitCode, str, object]], None] = sys.exit):
        """
        :param exiter: A function to be called to conduct the final exit of the runtime. (Optional)
        """
        # Since we have some exit paths that run via the sys.excepthook,
        # symbols we use can become garbage collected before we use them; ie:
        # we can find `sys` and `traceback` are `None`.  As a result we capture
        # all symbols we need here to ensure we function in excepthook context.
        # See: http://stackoverflow.com/questions/2572172/referencing-other-modules-in-atexit
        self._exit = exiter

    def __call__(self, *args, **kwargs):
        """Map class calls to self.exit() to support sys.exit() fungibility."""
        return self.exit(*args, **kwargs)

    def exit(self, result=PANTS_SUCCEEDED_EXIT_CODE, msg=None, out=None):
        """Exits the runtime.

        :param result: The exit status. Typically either PANTS_SUCCEEDED_EXIT_CODE or
                       PANTS_FAILED_EXIT_CODE, but can be a string as well. (Optional)
        :param msg: A string message to print to stderr or another custom file desciptor before exiting.
                    (Optional)
        :param out: The file descriptor to emit `msg` to. (Optional)
        """
        if msg:
            out = out or sys.stderr
            if hasattr(out, "buffer"):
                out = out.buffer

            msg = ensure_binary(msg)
            try:
                out.write(msg)
                out.write(b"\n")
                # TODO: Determine whether this call is a no-op because the stream gets flushed on exit, or
                # if we could lose what we just printed, e.g. if we get interrupted by a signal while
                # exiting and the stream is buffered like stdout.
                out.flush()
            except Exception as e:
                # If the file is already closed, or any other error occurs, just log it and continue to
                # exit.
                if msg:
                    logger.warning(
                        "Encountered error when trying to log this message: {}, \n "
                        "exception: {} \n out: {}".format(msg, e, out)
                    )
                    # In pantsd, this won't go anywhere, because there's really nowhere for us to log if we
                    # can't log :(
                    # Not in pantsd, this will end up in sys.stderr.
                    traceback.print_stack()
                logger.exception(e)
        self._exit(result)

    def exit_and_fail(self, msg=None, out=None):
        """Exits the runtime with a nonzero exit code, indicating failure.

        :param msg: A string message to print to stderr or another custom file desciptor before exiting.
                    (Optional)
        :param out: The file descriptor to emit `msg` to. (Optional)
        """
        self.exit(result=PANTS_FAILED_EXIT_CODE, msg=msg, out=out)
