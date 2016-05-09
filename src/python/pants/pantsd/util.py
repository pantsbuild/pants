# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.goal.goal import Goal
from pants.goal.run_tracker import RunTracker


def clean_global_runtime_state():
  """Resets the global runtime state of a pants runtime for cleaner forking."""
  # Reset RunTracker state.
  RunTracker.global_instance().reset(reset_options=False)

  # Reset Goals and Tasks.
  Goal.clear()
