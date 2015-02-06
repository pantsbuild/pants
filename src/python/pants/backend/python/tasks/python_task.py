# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import tempfile
from contextlib import contextmanager

from pex.pex_builder import PEXBuilder
from twitter.common.collections import OrderedSet

from pants.backend.core.tasks.task import Task
from pants.backend.python.interpreter_cache import PythonInterpreterCache
from pants.base.exceptions import TaskError


class PythonTask(Task):
  def __init__(self, *args, **kwargs):
    super(PythonTask, self).__init__(*args, **kwargs)
    self._compatibilities = self.get_options().interpreter or [b'']
    self._interpreter_cache = None
    self._interpreter = None

  @property
  def interpreter_cache(self):
    if self._interpreter_cache is None:
      self._interpreter_cache = PythonInterpreterCache(self.context.config,
                                                       logger=self.context.log.debug)

      # Cache setup's requirement fetching can hang if run concurrently by another pants proc.
      self.context.acquire_lock()
      try:
        # We pass in filters=compatibilities because setting up some python versions
        # (e.g., 3<=python<3.3) crashes, and this gives us an escape hatch.
        self._interpreter_cache.setup(filters=self._compatibilities)
      finally:
        self.context.release_lock()
    return self._interpreter_cache

  @property
  def interpreter(self):
    """Subclasses can use this if they're fine with the default interpreter (the usual case)."""
    if self._interpreter is None:
      self._interpreter = self.select_interpreter(self._compatibilities)
    return self._interpreter

  def select_interpreter_for_targets(self, targets):
    """Pick an interpreter compatible with all the specified targets."""
    allowed_interpreters = OrderedSet(self.interpreter_cache.interpreters)
    targets_with_compatibilities = []  # Used only for error messages.

    # Constrain allowed_interpreters based on each target's compatibility requirements.
    for target in targets:
      if target.is_python and hasattr(target, 'compatibility') and target.compatibility:
        targets_with_compatibilities.append(target)
        compatible_with_target = list(self.interpreter_cache.matches(target.compatibility))
        allowed_interpreters &= compatible_with_target

    if not allowed_interpreters:
      # Create a helpful error message.
      unique_compatibilities = set(tuple(t.compatibility) for t in targets_with_compatibilities)
      unique_compatibilities_strs = [','.join(x) for x in unique_compatibilities if x]
      targets_with_compatibilities_strs = [str(t) for t in targets_with_compatibilities]
      raise TaskError('Unable to detect a suitable interpreter for compatibilities: %s '
                      '(Conflicting targets: %s)' % (' && '.join(unique_compatibilities_strs),
                                                     ', '.join(targets_with_compatibilities_strs)))

    # Return the lowest compatible interpreter.
    return self.interpreter_cache.select_interpreter(allowed_interpreters)[0]

  def select_interpreter(self, filters):
    """Subclasses can use this to be more specific about interpreter selection."""
    interpreters = self.interpreter_cache.select_interpreter(
      list(self.interpreter_cache.matches(filters)))
    if len(interpreters) != 1:
      raise TaskError('Unable to detect a suitable interpreter.')
    interpreter = interpreters[0]
    self.context.log.debug('Selected %s' % interpreter)
    return interpreter

  @contextmanager
  def temporary_pex_builder(self, interpreter=None, pex_info=None, parent_dir=None):
    """Yields a PEXBuilder and cleans up its chroot when it goes out of context."""
    path = tempfile.mkdtemp(dir=parent_dir)
    builder = PEXBuilder(path=path, interpreter=interpreter, pex_info=pex_info)
    yield builder
    builder.chroot().delete()
