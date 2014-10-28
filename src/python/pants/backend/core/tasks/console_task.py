# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import errno
import os
from contextlib import contextmanager

from pants.backend.core.tasks.task import QuietTaskMixin, Task
from pants.base.exceptions import TaskError
from pants.util.dirutil import safe_open


class ConsoleTask(Task, QuietTaskMixin):
  """A task whose only job is to print information to the console.

  ConsoleTasks are not intended to modify build state.
  """
  @classmethod
  def register_options(cls, register):
    super(ConsoleTask, cls).register_options(register)
    register('--sep', default='\\n', metavar='<separator>',
             help='String to use to separate results.',
             legacy='console_{0}_separator'.format(cls.__name__))
    register('--output-file', metavar='<path>',
             help='Write the console output to this file instead.',
             legacy='console_outstream')

  def __init__(self, *args, **kwargs):
    super(ConsoleTask, self).__init__(*args, **kwargs)
    separator_option = "console_%s_separator" % self.__class__.__name__
    self._console_separator = getattr(self.context.options,
                                      separator_option).decode('string-escape')
    if self.context.options.console_outstream:
      try:
        self._outstream = safe_open(os.path.abspath(self.context.options.console_outstream), 'w')
      except IOError as e:
        raise TaskError('Error opening stream {out_file} due to'
                        ' {error_str}'.format(out_file=self.context.options.console_outstream,
                                              error_str=e))
    else:
      self._outstream = self.context.console_outstream

  @contextmanager
  def _guard_sigpipe(self):
    try:
      yield
    except IOError as e:
      # If the pipeline only wants to read so much, that's fine; otherwise, this error is probably
      # legitimate.
      if e.errno != errno.EPIPE:
        raise e

  def execute(self):
    with self._guard_sigpipe():
      try:
        targets = self.context.targets()
        for value in self.console_output(targets):
          self._outstream.write(str(value))
          self._outstream.write(self._console_separator)
      finally:
        self._outstream.flush()
        if self.context.options.console_outstream:
          self._outstream.close()

  def console_output(self, targets):
    raise NotImplementedError('console_output must be implemented by subclasses of ConsoleTask')
