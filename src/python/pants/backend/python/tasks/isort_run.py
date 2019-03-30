# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import functools
import logging
import os
import re

from pants.backend.python.targets.python_binary import PythonBinary
from pants.backend.python.targets.python_library import PythonLibrary
from pants.backend.python.targets.python_tests import PythonTests
from pants.backend.python.tasks.isort_prep import IsortPrep
from pants.base.build_environment import get_buildroot
from pants.base.exceptions import TaskError
from pants.base.workunit import WorkUnitLabel
from pants.task.fmt_task_mixin import FmtTaskMixin
from pants.task.console_task import ConsoleTask
from pants.util.contextutil import pushd


class IsortRun(FmtTaskMixin, ConsoleTask):
  """Autoformats Python source files with isort.

  Behavior:
  ./pants fmt.isort <targets> -- <args, e.g. "--recursive ."> will sort the files only related
    to specified targets, but the way of finding the config(s) is vanilla. If no target is
    specified or no python source file is found in <targets>, it would be a no-op.
  """

  NOOP_MSG_HAS_TARGET_BUT_NO_SOURCE = "No-op: no Python source file found in target(s)."

  _PYTHON_SOURCE_EXTENSION = '.py'

  @classmethod
  def prepare(cls, options, round_manager):
    super(IsortRun, cls).prepare(options, round_manager)
    round_manager.require_data(IsortPrep.tool_instance_cls)

  def console_output(self, _targets):
    targets = self.get_targets(self.is_non_synthetic_python_target)
    with self.invalidated(targets=targets) as invalidation_check:
      if not invalidation_check.invalid_vts:
        logging.debug(self.NOOP_MSG_HAS_TARGET_BUT_NO_SOURCE)
        return

      invalid_tgts = [vt.target for vt in invalidation_check.invalid_vts]
      sources = self._calculate_isortable_python_sources(invalid_tgts)
      if not sources:
        logging.debug(self.NOOP_MSG_HAS_TARGET_BUT_NO_SOURCE)
        return

      isort = self.context.products.get_data(IsortPrep.tool_instance_cls)
      args = self.get_passthru_args() + sources

      stdout, stderr, exit_code, cmdline = isort.output(args)
      if exit_code == 0:
        yield "All Python imports correctly sorted for requested targets."
      elif ("-c" in args or "--check-only" in args) and exit_code == 1:
        failing_targets = '\n'.join(self._parse_failing_targets(stdout.strip()))
        raise TaskError("The following files have incorrect import orders:\n\n{}".format(failing_targets))
      else:
        raise TaskError("{} ... exited non-zero ({}) with stderr {}.".format(cmdline, exit_code, stderr),
                        exit_code=exit_code)

  def _calculate_isortable_python_sources(self, targets):
    """Generate a set of source files from the given targets."""
    sources = set()
    for target in targets:
      sources.update(
        source for source in target.sources_relative_to_buildroot()
        if os.path.splitext(source)[1] == self._PYTHON_SOURCE_EXTENSION
      )
    return list(sources)

  @staticmethod
  def _parse_failing_targets(stdout):
    error_lines = (line for line in stdout.split("\n") if "ERROR" in line)
    prefix = r"(?<={}/)".format(get_buildroot())
    postfix = r'(?=\sImports)'
    parsed_files = (re.search(f"{prefix}.*{postfix}", line)[0] for line in error_lines)
    return sorted(parsed_files)

  @staticmethod
  def is_non_synthetic_python_target(target):
    return (not target.is_synthetic
            and isinstance(target, (PythonLibrary, PythonBinary, PythonTests)))

  @classmethod
  def supports_passthru_args(cls):
    return True
