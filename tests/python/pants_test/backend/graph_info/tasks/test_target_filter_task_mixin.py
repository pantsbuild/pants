# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.graph_info.tasks.target_filter_task_mixin import TargetFilterTaskMixin
from pants.build_graph.build_file_aliases import BuildFileAliases, TargetMacro
from pants.build_graph.target import Target
from pants.testutil.task_test_base import TaskTestBase


class TargetFilterTaskMixinTest(TaskTestBase):
    @classmethod
    def task_type(cls):
        class TestTargetFilteringTask(TargetFilterTaskMixin):
            def execute(self):
                raise NotImplementedError()

        return TestTargetFilteringTask

    class RedTarget(Target):
        pass

    class BlueTarget(Target):
        pass

    class GreenTarget(Target):
        pass

    class PurpleTarget(Target):
        pass

    @classmethod
    def alias_groups(cls):
        purple_macro = TargetMacro.Factory.wrap(lambda ctx: None, cls.PurpleTarget)
        return BuildFileAliases(
            targets={"green": cls.GreenTarget, "purple": purple_macro},
            objects={"red": object()},
            context_aware_object_factories={"blue": lambda ctx: None},
        )

    def setUp(self):
        super().setUp()
        self.task = self.create_task(self.context())

    def test_simple_alias(self):
        green_targets = self.task.target_types_for_alias("green")
        self.assertEqual({self.GreenTarget}, green_targets)

    def test_macro_alias(self):
        purple_targets = self.task.target_types_for_alias("purple")
        self.assertEqual({self.PurpleTarget}, purple_targets)

    def test_alias_miss(self):
        with self.assertRaises(self.task.InvalidTargetType):
            self.task.target_types_for_alias("red")  # Not a target - an object.
        with self.assertRaises(self.task.InvalidTargetType):
            self.task.target_types_for_alias(
                "blue"
            )  # Not a target - a context aware object factory.
        with self.assertRaises(self.task.InvalidTargetType):
            self.task.target_types_for_alias("yellow")  # Not a registered alias.
