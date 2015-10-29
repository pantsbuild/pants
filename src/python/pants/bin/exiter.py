# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import sys
import traceback


class Exiter(object):
  def __init__(self):
    # Since we have some exit paths that run via the sys.excepthook,
    # symbols we use can become garbage collected before we use them; ie:
    # we can find `sys` and `traceback` are `None`.  As a result we capture
    # all symbols we need here to ensure we function in excepthook context.
    # See: http://stackoverflow.com/questions/2572172/referencing-other-modules-in-atexit
    self._exit = sys.exit
    self._format_tb = traceback.format_tb
    self._should_print_backtrace = True

  def __call__(self, *args, **kwargs):
    """Map class calls to self.exit() to support sys.exit() fungibility."""
    return self.exit(*args, **kwargs)

  def apply_options(self, options):
    self._should_print_backtrace = options.for_global_scope().print_exception_stacktrace

  def exit(self, result=0, msg=None, out=sys.stderr):
    if msg:
      print(msg, file=out)
    self._exit(result)

  def exit_and_fail(self, msg=None):
    self.exit(result=1, msg=msg)

  def unhandled_exception_hook(self, exception_class, exception, tb):
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
    # Call the registration of the unhandled exception hook as early as possible in the code.
    sys.excepthook = self.unhandled_exception_hook
