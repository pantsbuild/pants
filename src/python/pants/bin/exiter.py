# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import datetime
import logging
import os
import sys
import traceback

from pants.util.dirutil import safe_open


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

  def __init__(self, exiter=sys.exit, formatter=traceback.format_tb, print_backtraces=True):
    """
    :param func exiter: A function to be called to conduct the final exit of the runtime. (Optional)
    :param func formatter: A function to be called to format any encountered tracebacks. (Optional)
    :param bool print_backtraces: Whether or not to print backtraces by default. Can be
                                  overridden by Exiter.apply_options(). (Optional)
    """
    # Since we have some exit paths that run via the sys.excepthook,
    # symbols we use can become garbage collected before we use them; ie:
    # we can find `sys` and `traceback` are `None`.  As a result we capture
    # all symbols we need here to ensure we function in excepthook context.
    # See: http://stackoverflow.com/questions/2572172/referencing-other-modules-in-atexit
    self._exit = exiter
    self._format_tb = formatter
    self._should_print_backtrace = print_backtraces
    self._workdir = None

  def __call__(self, *args, **kwargs):
    """Map class calls to self.exit() to support sys.exit() fungibility."""
    return self.exit(*args, **kwargs)

  def apply_options(self, options):
    """Applies global configuration options to internal behavior.

    :param Options options: An instance of an Options object to fetch global options from.
    """
    self._should_print_backtrace = options.for_global_scope().print_exception_stacktrace
    self._workdir = options.for_global_scope().pants_workdir

  def exit(self, result=0, msg=None, out=None):
    """Exits the runtime.

    :param result: The exit status. Typically a 0 indicating success or a 1 indicating failure, but
                   can be a string as well. (Optional)
    :param msg: A string message to print to stderr or another custom file desciptor before exiting.
                (Optional)
    :param out: The file descriptor to emit `msg` to. (Optional)
    """
    if msg:
      print(msg, file=out or sys.stderr)
    self._exit(result)

  def exit_and_fail(self, msg=None):
    """Exits the runtime with an exit code of 1, indicating failure.

    :param str msg: A string message to print to stderr before exiting. (Optional)
    """
    self.exit(result=1, msg=msg)

  def handle_unhandled_exception(self, exc_class=None, exc=None, tb=None, add_newline=False):
    """Default sys.excepthook implementation for unhandled exceptions."""
    exc_class = exc_class or sys.exc_type
    exc = exc or sys.exc_value
    tb = tb or sys.exc_traceback

    def format_msg(print_backtrace=True):
      msg = 'Exception caught: ({})\n'.format(type(exc))
      msg += '{}\n'.format(''.join(self._format_tb(tb))) if print_backtrace else '\n'
      msg += 'Exception message: {}\n'.format(exc if str(exc) else 'none')
      msg += '\n' if add_newline else ''
      return msg

    # Always output the unhandled exception details into a log file.
    self._log_exception(format_msg())
    self.exit_and_fail(format_msg(self._should_print_backtrace))

  def _log_exception(self, msg):
    if self._workdir:
      try:
        output_path = os.path.join(self._workdir, 'logs', 'exceptions.log')
        with safe_open(output_path, 'a') as exception_log:
          exception_log.write('timestamp: {}\n'.format(datetime.datetime.now().isoformat()))
          exception_log.write('args: {}\n'.format(sys.argv))
          exception_log.write('pid: {}\n'.format(os.getpid()))
          exception_log.write(msg)
          exception_log.write('\n')
      except Exception as e:
        # This is all error recovery logic so we catch all exceptions from the logic above because
        # we don't want to hide the original error.
        logger.error('Problem logging original exception: {}'.format(e))

  def set_except_hook(self):
    """Sets the global exception hook."""
    sys.excepthook = self.handle_unhandled_exception
