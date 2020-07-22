# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
import unittest.mock

from pants.backend.jvm.subsystems.jvm_platform import JvmPlatform, JvmPlatformSettings
from pants.backend.jvm.targets.jvm_target import JvmTarget
from pants.backend.jvm.targets.runtime_platform_mixin import RuntimePlatformMixin
from pants.backend.jvm.tasks.classpath_products import ClasspathProducts
from pants.backend.jvm.tasks.jvm_task import JvmTask
from pants.testutil.jvm.jvm_task_test_base import JvmTaskTestBase


class DummyJvmTask(JvmTask):
    def execute(self):
        pass


class JvmTaskTest(JvmTaskTestBase):
    """Test some base functionality in JvmTask."""

    @classmethod
    def task_type(cls):
        return DummyJvmTask

    def setUp(self):
        super().setUp()

        self.t1 = self.make_target("t1")
        self.t2 = self.make_target("t2")
        self.t3 = self.make_target("t3")

        context = self.context(target_roots=[self.t1, self.t2, self.t3])

        self.classpath = [os.path.join(self.pants_workdir, entry) for entry in ("a", "b")]
        self.populate_runtime_classpath(context, self.classpath)

        self.task = self.create_task(context)

    def test_classpath(self):
        self.assertEqual(self.classpath, self.task.classpath([self.t1]))
        self.assertEqual(self.classpath, self.task.classpath([self.t2]))
        self.assertEqual(self.classpath, self.task.classpath([self.t3]))
        self.assertEqual(self.classpath, self.task.classpath([self.t1, self.t2, self.t3]))

    def test_classpath_prefix(self):
        self.assertEqual(
            ["first"] + self.classpath, self.task.classpath([self.t1], classpath_prefix=["first"])
        )

    def test_classpath_custom_product(self):
        self.assertEqual(
            [],
            self.task.classpath([self.t1], classpath_product=ClasspathProducts(self.pants_workdir)),
        )

    def test_distribution_from_jvm_platform_passed_through(self):
        fake_dist = "a dist"
        platforms = [self.java8_platform()]
        with unittest.mock.patch.object(JvmPlatform, "preferred_jvm_distribution") as plat_mock:
            plat_mock.return_value = fake_dist
            dist = self.task.preferred_jvm_distribution(platforms)

            plat_mock.assert_called_once()
            self.assertEqual(fake_dist, dist)

    def test_distribution_from_targets_passes_through_platforms(self):
        fake_dist = "a dist"
        java8_platform = self.java8_platform()
        targets = [self.make_target("platformed_target", JvmTarget, platform="java8")]
        with unittest.mock.patch.object(JvmPlatform, "preferred_jvm_distribution") as plat_mock:
            with unittest.mock.patch.object(
                JvmPlatform.global_instance(), "get_platform_for_target"
            ) as target_plat_mock:
                target_plat_mock.return_value = java8_platform

                plat_mock.return_value = fake_dist
                dist = self.task.preferred_jvm_distribution_for_targets(targets)

                plat_mock.assert_called_once_with([java8_platform], strict=None, jdk=False)
                self.assertEqual(fake_dist, dist)

    def test_runtime_platforms_for_targets(self):
        java8_platform = self.java8_platform()

        class OneOffTarget(JvmTarget):
            def __init__(self, platform):
                self._platform = platform

            @property
            def platform(self):
                return self._platform

        class OneOffRuntimePlatformTarget(RuntimePlatformMixin, JvmTarget):
            def __init__(self, runtime_platform):
                self._runtime_platform = runtime_platform

            @property
            def runtime_platform(self):
                return self._runtime_platform

        with unittest.mock.patch.object(
            JvmPlatform, "default_runtime_platform", new_callable=unittest.mock.PropertyMock
        ) as plat_mock:
            plat_mock.return_value = "default-platform"

            targets = [OneOffTarget(java8_platform), OneOffRuntimePlatformTarget(java8_platform)]
            self.assertEqual(
                [java8_platform, java8_platform], self.task.runtime_platforms_for_targets(targets)
            )

            self.assertEqual(
                [JvmPlatform.global_instance().default_runtime_platform],
                self.task.runtime_platforms_for_targets([]),
            )

    def java8_platform(self):
        return JvmPlatformSettings(source_level="8", target_level="8", args=[], jvm_options=[])
