# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import re
from abc import abstractmethod
from enum import Enum

from pants.backend.native.register import rules as native_backend_rules
from pants.backend.native.subsystems.libc_dev import LibcDev
from pants.backend.native.subsystems.native_build_step import ToolchainVariant
from pants.backend.python.tasks.build_local_python_distributions import (
    BuildLocalPythonDistributions,
)
from pants.backend.python.tasks.resolve_requirements import ResolveRequirements
from pants.backend.python.tasks.select_interpreter import SelectInterpreter
from pants.python.python_repos import PythonRepos
from pants.testutil.task_test_base import DeclarativeTaskTestMixin
from pants.util.collections import assert_single_element
from pants.util.enums import match
from pants.util.meta import classproperty
from pants_test.backend.python.tasks.python_task_test_base import PythonTaskTestBase
from pants_test.backend.python.tasks.util.wheel import (
    name_and_platform,
    normalized_current_platform,
)


class BuildLocalPythonDistributionsTestBase(PythonTaskTestBase, DeclarativeTaskTestMixin):
    @classmethod
    def task_type(cls):
        return BuildLocalPythonDistributions

    @classproperty
    def run_before_task_types(cls):
        return [SelectInterpreter]

    @classproperty
    def run_after_task_types(cls):
        return [ResolveRequirements]

    @classmethod
    def rules(cls):
        return (*super().rules(), *native_backend_rules())

    @classproperty
    @abstractmethod
    def dist_specs(cls):
        """Fed into `self.populate_target_dict()`."""

    def setUp(self):
        super().setUp()
        # Share the target mapping across all test cases.
        self.target_dict = self.populate_target_dict(self.dist_specs)

    def _get_dist_snapshot_version(self, task, python_dist_target):
        """Get the target's fingerprint, and guess the resulting version string of the built dist.

        Local python_dist() builds are tagged with the versioned target's fingerprint using the
        --tag-build option in the egg_info command. This fingerprint string is slightly modified by
        distutils to ensure a valid version string, and this method finds what that modified version
        string is so we can verify that the produced local dist is being tagged with the correct
        snapshot version.

        The argument we pass to that option begins with a +, which is unchanged. See
        https://www.python.org/dev/peps/pep-0440/ for further information.
        """
        with task.invalidated(
            [python_dist_target], invalidate_dependents=True
        ) as invalidation_check:
            versioned_dist_target = assert_single_element(invalidation_check.all_vts)

        versioned_target_fingerprint = versioned_dist_target.cache_key.hash

        # This performs the normalization that distutils performs to the version string passed to the
        # --tag-build option.
        return re.sub(r"[^a-zA-Z0-9]", ".", versioned_target_fingerprint.lower())

    def _create_distribution_synthetic_target(self, python_dist_target, extra_targets=[]):
        all_specified_targets = list(self.target_dict.values()) + list(extra_targets)
        result = self.invoke_tasks(
            # We set `target_closure` to check that all the targets in the build graph are exactly the
            # ones we've just created before building python_dist()s (which creates further targets).
            target_closure=all_specified_targets,
            target_roots=[python_dist_target] + extra_targets,
            for_subsystems=[PythonRepos, LibcDev],
            # TODO(#6848): we should be testing all of these with both of our toolchains.
            options={"native-build-step": {"toolchain_variant": ToolchainVariant.llvm}},
        )
        context = result.context
        python_create_distributions_task_instance = result.this_task

        synthetic_tgts = set(context.build_graph.targets()) - set(all_specified_targets)
        self.assertEqual(1, len(synthetic_tgts))
        synthetic_target = next(iter(synthetic_tgts))

        snapshot_version = self._get_dist_snapshot_version(
            python_create_distributions_task_instance, python_dist_target
        )

        return context, synthetic_target, snapshot_version

    class ExpectedPlatformType(Enum):
        """Whether to check that the produced wheel has the 'any' platform, or the current one."""

        any = "any"
        current = "current"

    def _assert_dist_and_wheel_identity(
        self, expected_name, expected_version, expected_platform, dist_target, **kwargs
    ):
        context, synthetic_target, fingerprint_suffix = self._create_distribution_synthetic_target(
            dist_target, **kwargs
        )
        resulting_dist_req = assert_single_element(synthetic_target.requirements.value)
        expected_snapshot_version = f"{expected_version}+{fingerprint_suffix}"
        self.assertEquals(
            f"{expected_name}=={expected_snapshot_version}", str(resulting_dist_req.requirement)
        )

        local_wheel_products = context.products.get("local_wheels")
        local_wheel = self.retrieve_single_product_at_target_base(local_wheel_products, dist_target)
        dist, version, platform = name_and_platform(local_wheel)
        self.assertEquals(dist, expected_name)
        self.assertEquals(version, expected_snapshot_version)

        expected_platform = match(
            expected_platform,
            {
                BuildLocalPythonDistributionsTestBase.ExpectedPlatformType.any: "any",
                BuildLocalPythonDistributionsTestBase.ExpectedPlatformType.current: normalized_current_platform(),
            },
        )
        self.assertEquals(platform, expected_platform)
