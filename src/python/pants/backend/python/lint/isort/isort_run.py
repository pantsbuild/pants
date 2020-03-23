# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import functools
import logging
import os

from pants.backend.python.lint.isort.isort_prep import IsortPrep
from pants.backend.python.lint.isort.subsystem import Isort
from pants.backend.python.targets.python_binary import PythonBinary
from pants.backend.python.targets.python_library import PythonLibrary
from pants.backend.python.targets.python_tests import PythonTests
from pants.base.build_environment import get_buildroot
from pants.base.exceptions import TaskError
from pants.base.workunit import WorkUnitLabel
from pants.task.fmt_task_mixin import FmtTaskMixin
from pants.task.task import Task
from pants.util.contextutil import pushd


class IsortRun(FmtTaskMixin, Task):
    """Autoformats Python source files with isort.

    Behavior:
    ./pants fmt.isort <targets> -- <args, e.g. "--recursive ."> will sort the files only related
      to specified targets, but the way of finding the config(s) is vanilla. If no target is
      specified or no python source file is found in <targets>, it would be a no-op.
    """

    NOOP_MSG_HAS_TARGET_BUT_NO_SOURCE = "No-op: no Python source file found in target(s)."

    _PYTHON_SOURCE_EXTENSION = ".py"

    @classmethod
    def prepare(cls, options, round_manager):
        super().prepare(options, round_manager)
        round_manager.require_data(IsortPrep.tool_instance_cls)

    def execute(self):
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
            isort_subsystem = Isort.global_instance()
            args = [*isort_subsystem.options.args, "--filter-files", *sources]

            # NB: We execute isort out of process to avoid unwanted side-effects from importing it:
            #   https://github.com/timothycrosley/isort/issues/456
            with pushd(get_buildroot()):
                workunit_factory = functools.partial(
                    self.context.new_workunit,
                    name="run-isort",
                    labels=[WorkUnitLabel.TOOL, WorkUnitLabel.LINT],
                )
                cmdline, exit_code = isort.run(workunit_factory, args)
                if exit_code != 0:
                    raise TaskError(
                        f"Exited with return code {exit_code} while running `{cmdline}`.",
                        exit_code=exit_code,
                    )

    def _calculate_isortable_python_sources(self, targets):
        """Generate a set of source files from the given targets."""
        sources = set()
        for target in targets:
            sources.update(
                source
                for source in target.sources_relative_to_buildroot()
                if os.path.splitext(source)[1] == self._PYTHON_SOURCE_EXTENSION
            )
        return list(sources)

    @staticmethod
    def is_non_synthetic_python_target(target):
        return not target.is_synthetic and isinstance(
            target, (PythonLibrary, PythonBinary, PythonTests)
        )

    @property
    def skip_execution(self):
        return self.determine_if_skipped(formatter_subsystem=Isort.global_instance())
