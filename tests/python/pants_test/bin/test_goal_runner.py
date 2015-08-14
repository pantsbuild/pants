# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import mock
import pytest
from pkg_resources import WorkingSet

from pants.bin.goal_runner import GoalRunner
from pants.option.options_bootstrapper import OptionsBootstrapper
from pants.util.contextutil import temporary_dir


@pytest.mark.parametrize('version_flag', ['-V', '--version', '--pants-version'])
def test_version_request(version_flag):
  class ExitException(Exception):
    def __init__(self, exit_code):
      self.exit_code = exit_code

  with temporary_dir() as build_root:
    on_exit = mock.Mock()

    def exited(exit_code):
      raise ExitException(exit_code)
    on_exit.side_effect = exited

    goal_runner = GoalRunner(build_root, exiter=on_exit)
    options_bootstrapper = OptionsBootstrapper(args=[version_flag])

    with pytest.raises(ExitException) as excinfo:
      goal_runner.setup(options_bootstrapper=options_bootstrapper, working_set=WorkingSet())
    assert 0 == excinfo.value.exit_code
