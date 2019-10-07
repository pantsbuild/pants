# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
import textwrap

from pants.base.build_environment import get_buildroot
from pants.util.contextutil import temporary_dir
from pants_test.pants_run_integration_test import PantsRunIntegrationTest


class TestGoalOptionsMixinIntegration(PantsRunIntegrationTest):
    @classmethod
    def hermetic(cls):
        return True

    def _do_test_goal_options(self, flags, expected_one, expected_two):
        with temporary_dir(root_dir=get_buildroot()) as src_dir:
            foo_dir = os.path.join(src_dir, "foo")
            os.mkdir(foo_dir)
            with open(os.path.join(foo_dir, "BUILD"), "w") as fp:
                fp.write(
                    textwrap.dedent(
                        """
        target(name='a', dependencies=[':b'])
        target(name='b')
        """
                    )
                )

            config = {
                "GLOBAL": {
                    "pythonpath": '+["%(buildroot)s/tests/python"]',
                    "backend_packages": '+["pants_test.task.echo_plugin"]',
                }
            }
            with self.pants_results(
                ["echo"] + flags + ["{}:a".format(foo_dir)], config=config
            ) as pants_run:
                self.assert_success(pants_run)

                def get_echo(which):
                    path = os.path.join(pants_run.workdir, "echo", which, "output")
                    if not os.path.exists(path):
                        return None
                    else:
                        with open(path, "r") as fp:
                            return [os.path.basename(x.strip()) for x in fp.readlines()]

                self.assertEqual(expected_one, get_echo("one"))
                self.assertEqual(expected_two, get_echo("two"))

    def test_defaults(self):
        self._do_test_goal_options([], ["foo:a", "foo:b"], ["foo:a", "foo:b"])

    def test_set_at_goal_level(self):
        self._do_test_goal_options(["--skip"], None, None)

    def test_set_at_task_level(self):
        self._do_test_goal_options(["--echo-one-skip"], None, ["foo:a", "foo:b"])
        self._do_test_goal_options(["--no-echo-two-transitive"], ["foo:a", "foo:b"], ["foo:a"])

    def test_set_at_goal_and_task_level(self):
        self._do_test_goal_options(["--skip", "--no-echo-one-skip"], ["foo:a", "foo:b"], None)
        self._do_test_goal_options(
            ["--no-transitive", "--echo-two-transitive"], ["foo:a"], ["foo:a", "foo:b"]
        )
