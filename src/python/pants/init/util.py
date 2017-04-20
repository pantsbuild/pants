# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.goal.goal import Goal
from pants.goal.run_tracker import RunTracker
from pants.init.options_initializer import OptionsInitializer
from pants.subsystem.subsystem import Subsystem


def clean_global_runtime_state(reset_runtracker=True, reset_subsystem=False):
  """Resets the global runtime state of a pants runtime for cleaner forking.

  :param bool reset_runtracker: Whether or not to clean RunTracker global state.
  :param bool reset_subsystem: Whether or not to clean Subsystem global state.
  """
  if reset_runtracker:
    # Reset RunTracker state.
    RunTracker.global_instance().reset(reset_options=False)

  if reset_subsystem:
    # Reset subsystem state.
    Subsystem.reset()

  # Reset Goals and Tasks.
  Goal.clear()

  # Reset backend/plugins state.
  OptionsInitializer.reset()
