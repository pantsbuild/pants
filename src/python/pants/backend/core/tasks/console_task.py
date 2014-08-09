# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import errno
from contextlib import contextmanager

from pants.backend.core.tasks.task import QuietTaskMixin, Task


class ConsoleTask(Task, QuietTaskMixin):
  """A task whose only job is to print information to the console.

  ConsoleTasks are not intended to modify build state.
  """
  @classmethod
  def setup_parser(cls, option_group, args, mkflag):
    option_group.add_option(mkflag("sep"), dest="console_%s_separator" % cls.__name__,
                            default='\\n', help="String to use to separate results.")

  def __init__(self, *args, **kwargs):
    super(ConsoleTask, self).__init__(*args, **kwargs)
    separator_option = "console_%s_separator" % self.__class__.__name__
    self._console_separator = getattr(self.context.options,
                                      separator_option).decode('string-escape')
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

  def console_output(self, targets):
    raise NotImplementedError('console_output must be implemented by subclasses of ConsoleTask')
