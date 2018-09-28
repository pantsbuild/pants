# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import logging
import sys
from builtins import object

from future.utils import PY2

from pants.util.fileutil import is_fileobj_definitely_closed


logger = logging.getLogger(__name__)


class Exiter(object):
  """A class that provides standard runtime exit and global exception handling behavior.

  The expected method call order of this class is as follows:

   1) Call Exiter.set_except_hook() to set sys.excepthook to the internal exception hook. This
      should happen as early as possible to ensure any/all exceptions are handled by the hook.
   2) Call Exiter.apply_options() to set traceback printing behavior via an Options object.
   3) Perform other operations as normal.
   4) Call Exiter.exit(), Exiter.exit_and_fail() or exiter_inst() when you wish to exit the runtime.
  """

  def __init__(self, exiter=sys.exit, print_backtraces=True):
    """
    :param func exiter: A function to be called to conduct the final exit of the runtime. (Optional)
    :param bool print_backtraces: Whether or not to print backtraces by default. Can be
                                  overridden by Exiter.apply_options(). (Optional)
    """
    # Since we have some exit paths that run via the sys.excepthook,
    # symbols we use can become garbage collected before we use them; ie:
    # we can find `sys` and `traceback` are `None`.  As a result we capture
    # all symbols we need here to ensure we function in excepthook context.
    # See: http://stackoverflow.com/questions/2572172/referencing-other-modules-in-atexit
    self._exit = exiter
    self.should_print_backtrace = print_backtraces

  def __call__(self, *args, **kwargs):
    """Map class calls to self.exit() to support sys.exit() fungibility."""
    return self.exit(*args, **kwargs)

  def exit(self, result=0, msg=None, out=None):
    """Exits the runtime.

    :param result: The exit status. Typically a 0 indicating success or a 1 indicating failure, but
                   can be a string as well. (Optional)
    :param msg: A string message to print to stderr or another custom file desciptor before exiting.
                (Optional)
    :param out: The file descriptor to emit `msg` to. (Optional)
    """
    # print('msg/base={}'.format(msg), file=sys.stderr)
    if msg:
      if PY2:
        # sys.stderr expects bytes in Py2, unicode in Py3
        msg = msg.encode('utf-8')
      out = out or sys.stderr
      if not is_fileobj_definitely_closed(out):
        print(msg, file=out)
        # NB: Ensure we write everything out in case it's not an unbuffered stream like stderr.
        out.flush()
    self._exit(result)

  def exit_and_fail(self, msg=None):
    """Exits the runtime with an exit code of 1, indicating failure.

    :param str msg: A string message to print to stderr before exiting. (Optional)
    """
    self.exit(result=1, msg=msg)
