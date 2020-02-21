# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
import unittest.mock

from pants.backend.jvm.subsystems.jvm_platform import JvmPlatform, JvmPlatformSettings
from pants.backend.jvm.targets.jvm_target import JvmTarget
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
        platforms = [JvmPlatformSettings("8", "8", [])]
        with unittest.mock.patch.object(JvmPlatform, "preferred_jvm_distribution") as plat_mock:
            plat_mock.return_value = fake_dist
            dist = self.task.preferred_jvm_distribution(platforms)

            plat_mock.assert_called_once()
            self.assertEqual(fake_dist, dist)

    def test_distribution_from_targets_passes_through_platforms(self):
        fake_dist = "a dist"
        java8_platform = JvmPlatformSettings("8", "8", [])
        targets = [self.make_target("platformed_target", JvmTarget, platform="java8")]
        with unittest.mock.patch.object(JvmPlatform, "preferred_jvm_distribution") as plat_mock:
            with unittest.mock.patch.object(
                JvmPlatform.global_instance(), "get_platform_for_target"
            ) as target_plat_mock:
                target_plat_mock.return_value = java8_platform

                plat_mock.return_value = fake_dist
                dist = self.task.preferred_jvm_distribution_for_targets(targets)

                plat_mock.assert_called_once_with([java8_platform], strict=False, jdk=False)
                self.assertEqual(fake_dist, dist)
