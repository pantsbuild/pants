# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from abc import abstractmethod

from pants.backend.core.tasks.mutex_task_mixin import MutexTaskMixin
from pants.base.workunit import WorkUnitLabel
from pants.console import stty_utils


class ReplTaskMixin(MutexTaskMixin):
  """A task mutex mixin for all REPL providing tasks installed in pants.

  By mixing in this class, REPL implementations ensure they are the only REPL that is being run in
  the current pants session.
  """

  @classmethod
  def mutex_base(cls):
    return ReplTaskMixin

  @abstractmethod
  def setup_repl_session(self, targets):
    """Implementations should prepare their REPL runner and return all session setup state needed.

    NB: This is called with the pants lock help, so otherwise unsafe operations can be performed.

    :param targets: All the targets reachable in this run selected by this REPLs `select_targets`
                    method.
    :returns: Any session setup state needed by `launch_repl`
    """

  @abstractmethod
  def launch_repl(self, session_setup):
    """Implementations should launch an interactive REPL session.

    :param session_setup:  The state returned from `setup_repl_session`
    """

  def execute_for(self, targets):
    session_setup = self.setup_repl_session(targets)
    self.context.release_lock()
    with stty_utils.preserve_stty_settings():
      with self.context.new_workunit(name='repl', labels=[WorkUnitLabel.RUN]):
        print('')  # Start REPL output on a new line.
        try:
          return self.launch_repl(session_setup)
        except KeyboardInterrupt:
          # This is a valid way to end a REPL session in general, so just break out of execute and
          # continue.
          pass
