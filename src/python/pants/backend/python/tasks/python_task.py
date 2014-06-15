# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from pants.backend.core.tasks.task import Task
from pants.backend.python.interpreter_cache import PythonInterpreterCache
from pants.base.exceptions import TaskError


class PythonTask(Task):
  @classmethod
  def setup_parser(cls, option_group, args, mkflag):
    option_group.add_option(mkflag('timeout'), dest='python_conn_timeout', type='int',
                            default=0, help='Number of seconds to wait for http connections.')

  def __init__(self, context, workdir):
    super(PythonTask, self).__init__(context, workdir)
    self.conn_timeout = (self.context.options.python_conn_timeout or
                         self.context.config.getdefault('connection_timeout'))
    compatibilities = self.context.options.interpreter or [b'']

    self.interpreter_cache = PythonInterpreterCache(self.context.config,
                                                    logger=self.context.log.debug)
    # We pass in filters=compatibilities because setting up some python versions
    # (e.g., 3<=python<3.3) crashes, and this gives us an escape hatch.
    self.interpreter_cache.setup(filters=compatibilities)

    # Select a default interpreter to use.
    self._interpreter = self.select_interpreter(compatibilities)

  @property
  def interpreter(self):
    """Subclasses can use this if they're fine with the default interpreter (the usual case)."""
    return self._interpreter

  def select_interpreter(self, compatibilities):
    """Subclasses can use this to be more specific about interpreter selection."""
    interpreters = self.interpreter_cache.select_interpreter(
      list(self.interpreter_cache.matches(compatibilities)))
    if len(interpreters) != 1:
      raise TaskError('Unable to detect suitable interpreter.')
    interpreter = interpreters[0]
    self.context.log.debug('Selected %s' % interpreter)
    return interpreter
