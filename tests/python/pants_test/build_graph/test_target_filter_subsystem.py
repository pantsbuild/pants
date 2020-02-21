# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).


from pants.build_graph.target_filter_subsystem import TargetFilter, TargetFiltering
from pants.task.task import Task
from pants.testutil.task_test_base import TaskTestBase


class TestTargetFilter(TaskTestBase):
    class DummyTask(Task):
        options_scope = "dummy"
        # TODO: MyPy doesn't understand when a class property was defined via a method with
        # @classproperty and then is treated as a normal class var in a subclass.
        target_filtering_enabled = True  # type: ignore[assignment]

        def execute(self):
            self.context.products.safe_create_data("task_targets", self.get_targets)

    @classmethod
    def task_type(cls):
        return cls.DummyTask

    def test_task_execution_with_filter(self):
        a = self.make_target("a", tags=["skip-me"])
        b = self.make_target("b", dependencies=[a], tags=[])

        context = self.context(
            for_task_types=[self.DummyTask],
            for_subsystems=[TargetFilter],
            target_roots=[b],
            options={TargetFilter.options_scope: {"exclude_tags": ["skip-me"]}},
        )

        self.create_task(context).execute()
        self.assertEqual([b], context.products.get_data("task_targets"))

    def test_filtering_single_tag(self):
        a = self.make_target("a", tags=[])
        b = self.make_target("b", tags=["skip-me"])
        c = self.make_target("c", tags=["tag1", "skip-me"])

        filtered_targets = TargetFiltering({"skip-me"}).apply_tag_blacklist([a, b, c])
        self.assertEqual([a], filtered_targets)

    def test_filtering_multiple_tags(self):
        a = self.make_target("a", tags=["tag1", "skip-me"])
        b = self.make_target("b", tags=["tag1", "tag2", "skip-me"])
        c = self.make_target("c", tags=["tag2"])

        filtered_targets = TargetFiltering({"skip-me", "tag2"}).apply_tag_blacklist([a, b, c])
        self.assertEqual([], filtered_targets)

    def test_filtering_no_tags(self):
        a = self.make_target("a", tags=["tag1"])
        b = self.make_target("b", tags=["tag1", "tag2"])
        c = self.make_target("c", tags=["tag2"])

        filtered_targets = TargetFiltering(set()).apply_tag_blacklist([a, b, c])
        self.assertEqual([a, b, c], filtered_targets)
