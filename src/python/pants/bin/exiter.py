# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import sys
import traceback


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

  def __call__(self, *args, **kwargs):
    """Map class calls to self.exit() to support sys.exit() fungibility."""
    return self.exit(*args, **kwargs)

  def apply_options(self, options):
    """Applies global configuration options to internal behavior.

    :param Options options: An instance of an Options object to fetch global options from.
    """
    self._should_print_backtrace = options.for_global_scope().print_exception_stacktrace

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

  def _unhandled_exception_hook(self, exception_class, exception, tb):
    """Default sys.excepthook implementation for unhandled exceptions, used by set_except_hook()."""
    msg = ''
    if self._should_print_backtrace:
      msg = '\nException caught: ({})\n{}'.format(type(exception), ''.join(self._format_tb(tb)))
    if str(exception):
      msg += '\nException message: {}\n'.format(exception)
    else:
      msg += '\nNo specific exception message.\n'
    # TODO(Jin Feng) Always output the unhandled exception details into a log file.
    self.exit_and_fail(msg)

  def set_except_hook(self):
    """Sets the global exception hook."""
    sys.excepthook = self._unhandled_exception_hook
