# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
from contextlib import contextmanager
from textwrap import dedent

from pants.testutil.pants_run_integration_test import PantsRunIntegrationTest
from pants.util.contextutil import temporary_dir
from pants.util.dirutil import safe_open


class PrepCommandIntegrationTest(PantsRunIntegrationTest):

    _SENTINELS = {
        "test": "running-prep-in-goal-test.txt",
        "compile": "running-prep-in-goal-compile.txt",
        "binary": "running-prep-in-goal-binary.txt",
    }

    @classmethod
    def _emit_targets(cls, buildroot):
        prep_command_path = os.path.join(buildroot, "src/java/org/pantsbuild/prepcommand")
        with safe_open(os.path.join(prep_command_path, "BUILD"), "w") as fp:
            for name, touch_target in cls._SENTINELS.items():
                fp.write(
                    dedent(
                        """
                        prep_command(
                          name='{name}',
                          goals=['{goal}'],
                          prep_executable='touch',
                          prep_args=['{tmpdir}/{touch_target}'],
                        )
                        """.format(
                            name=name, goal=name, tmpdir=buildroot, touch_target=touch_target
                        )
                    )
                )
        return [f"{prep_command_path}:{name}" for name in cls._SENTINELS]

    @classmethod
    def _goal_ran(cls, basedir, goal):
        return os.path.exists(os.path.join(basedir, cls._SENTINELS[goal]))

    def _assert_goal_ran(self, basedir, goal):
        self.assertTrue(self._goal_ran(basedir, goal))

    def _assert_goal_did_not_run(self, basedir, goal):
        self.assertFalse(self._goal_ran(basedir, goal))

    @contextmanager
    def _execute_pants(self, goal):
        with temporary_dir(os.getcwd()) as buildroot, self.temporary_workdir(buildroot) as workdir:
            prep_commands_specs = self._emit_targets(buildroot)
            pants_run = self.run_pants_with_workdir([goal] + prep_commands_specs, workdir)
            self.assert_success(pants_run)
            yield buildroot

    def test_prep_command_in_compile(self):
        with self._execute_pants("compile") as buildroot:
            self._assert_goal_ran(buildroot, "compile")
            self._assert_goal_did_not_run(buildroot, "test")
            self._assert_goal_did_not_run(buildroot, "binary")

    def test_prep_command_in_test(self):
        with self._execute_pants("test") as buildroot:
            self._assert_goal_ran(buildroot, "compile")
            self._assert_goal_ran(buildroot, "test")
            self._assert_goal_did_not_run(buildroot, "binary")

    def test_prep_command_in_binary(self):
        with self._execute_pants("binary") as buildroot:
            self._assert_goal_ran(buildroot, "compile")
            self._assert_goal_ran(buildroot, "binary")
            self._assert_goal_did_not_run(buildroot, "test")
