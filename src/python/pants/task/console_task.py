# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import errno
import os
from contextlib import contextmanager

from pants.base.exceptions import TaskError
from pants.task.task import QuietTaskMixin, Task
from pants.util.dirutil import safe_open


class ConsoleTask(QuietTaskMixin, Task):
  """A task whose only job is to print information to the console.

  ConsoleTasks are not intended to modify build state.
  """

  @classmethod
  def register_options(cls, register):
    super(ConsoleTask, cls).register_options(register)
    register('--sep', default='\\n', metavar='<separator>',
             help='String to use to separate results.')
    register('--output-file', metavar='<path>',
             help='Write the console output to this file instead.')

  def __init__(self, *args, **kwargs):
    super(ConsoleTask, self).__init__(*args, **kwargs)
    self._defines_console_output = not hasattr(self.console_output, '_canary')
    self._defines_render = not hasattr(self.render, '_canary')
    if self._defines_console_output == self._defines_render:
      raise AssertionError(
          'ConsoleTasks must define exactly one of either `console_output` or `render`.')

    self._console_separator = self.get_options().sep.decode('string-escape')
    if self.get_options().output_file:
      try:
        self._outstream = safe_open(os.path.abspath(self.get_options().output_file), 'w')
      except IOError as e:
        raise TaskError('Error opening stream {out_file} due to'
                        ' {error_str}'.format(out_file=self.get_options().output_file, error_str=e))
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
        if self._defines_console_output:
          generator = self.console_output(self.context.targets())
        else:
          generator = self.render()
        for value in generator or tuple():
          self._outstream.write(value.encode('utf-8'))
          self._outstream.write(self._console_separator)
      finally:
        self._outstream.flush()
        if self.get_options().output_file:
          self._outstream.close()

  def console_output(self, targets):
    """Creates a generator or collection of lines of output for the given root targets.

    Exactly one of `console_output` or `render` should be implemented.

    :API: public
    """
  console_output._canary = None

  def render(self):
    """Creates a generator or collection of output lines (generally from the products for the task).

    Exactly one of `console_output` or `render` should be implemented.

    :API: experimental
    """
  render._canary = None
