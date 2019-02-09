# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import logging
import sys
from builtins import object

from future.utils import PY3

from pants.util.strutil import ensure_binary


logger = logging.getLogger(__name__)


# ???/so we're all on the same page
PANTS_SUCCESS_EXIT_CODE = 0
PANTS_FAILED_EXIT_CODE = 1


class Exiter(object):
  """A class that provides standard runtime exit behavior.

  `pants.base.exception_sink.ExceptionSink` handles exceptions and fatal signals, delegating to an
  Exiter instance. Call Exiter.exit() or Exiter.exit_and_fail() when you wish to exit the runtime.
  """

  def __init__(self, exiter=sys.exit):
    """
    :param func exiter: A function to be called to conduct the final exit of the runtime. (Optional)
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

  # TODO: add PANTS_SUCCESS_EXIT_CODE and PANTS_FAILED_EXIT_CODE to the docstring!
  def exit(self, result=PANTS_SUCCESS_EXIT_CODE, msg=None, out=None):
    """Exits the runtime.

    :param result: The exit status. Typically a 0 indicating success or a 1 indicating failure, but
                   can be a string as well. (Optional)
    :param msg: A string message to print to stderr or another custom file desciptor before exiting.
                (Optional)
    :param out: The file descriptor to emit `msg` to. (Optional)
    """
    if msg:
      out = out or sys.stderr
      if PY3 and hasattr(out, 'buffer'):
        out = out.buffer

      msg = ensure_binary(msg)
      try:
        out.write(msg)
        out.write(b'\n')
        # TODO: Determine whether this call is a no-op because the stream gets flushed on exit, or
        # if we could lose what we just printed, e.g. if we get interrupted by a signal while
        # exiting and the stream is buffered like stdout.
        out.flush()
      except Exception as e:
        # If the file is already closed, or any other error occurs, just log it and continue to
        # exit.
        logger.exception(e)
    self._exit(result)

  def exit_and_fail(self, msg=None, out=None):
    """Exits the runtime with a nonzero exit code, indicating failure.

    :param msg: A string message to print to stderr or another custom file desciptor before exiting.
                (Optional)
    :param out: The file descriptor to emit `msg` to. (Optional)
    """
    self.exit(result=PANTS_FAILED_EXIT_CODE, msg=msg, out=out)
