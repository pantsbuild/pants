# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.jvm.targets.jvm_binary import JvmBinary
from pants.backend.jvm.targets.jvm_prep_command import JvmPrepCommand
from pants.backend.jvm.tasks.run_jvm_prep_command import RunJvmPrepCommandBase
from pants.base.exceptions import TargetDefinitionException
from pants.testutil.task_test_base import TaskTestBase


class FakeRunJvmPrepCommand(RunJvmPrepCommandBase):
    goal = "test"


class JvmPrepCommandTest(TaskTestBase):
    def setUp(self):
        super().setUp()
        # This is normally taken care of in RunJvmPrepCommandBase.register_options() when running pants,
        # but these don't get called in testing unless you call `self.create_task()`.
        # Some of these unit tests need to create targets before creating the task.
        JvmPrepCommand.add_goal("test")
        JvmPrepCommand.add_goal("binary")

    def tearDown(self):
        JvmPrepCommand.reset()

    @classmethod
    def task_type(cls):
        return FakeRunJvmPrepCommand

    def test_valid_target(self):
        self.make_target("foo", JvmPrepCommand, mainclass="org.pantsbuild.FooMain")

    def test_invalid_target(self):
        with self.assertRaisesRegex(TargetDefinitionException, r"mainclass must be specified"):
            self.make_target(
                "foo", JvmPrepCommand,
            )

        with self.assertRaisesRegex(
            TargetDefinitionException, r'.*Got goal "baloney". Goal must be one of.*'
        ):
            self.make_target(
                "foo", JvmPrepCommand, mainclass="org.pantsbuild.FooMain", goal="baloney"
            )

    def test_runnable_prep_cmd(self):
        prep_cmd_test = self.make_target(
            "prep-cmd-test", JvmPrepCommand, mainclass="org.pantsbuild.FooMain"
        )
        prep_cmd_binary = self.make_target(
            "prep-cmd-binary", JvmPrepCommand, mainclass="org.pantsbuild.FooMain", goal="binary"
        )
        not_a_prep_cmd = self.make_target("not-a-prep-command", JvmBinary)
        task = self.create_task(context=self.context())

        self.assertTrue(task.runnable_prep_cmd(prep_cmd_test))
        # This is a prep_command target, but not for this goal
        self.assertFalse(task.runnable_prep_cmd(prep_cmd_binary))
        self.assertFalse(task.runnable_prep_cmd(not_a_prep_cmd))
