# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import pytest

from pants.backend.python.pants_requirement import PantsRequirement
from pants.backend.python.target_types import PythonRequirementLibrary, PythonRequirementsField
from pants.base.build_environment import pants_version
from pants.build_graph.build_file_aliases import BuildFileAliases
from pants.engine.addresses import Address
from pants.engine.internals.scheduler import ExecutionError
from pants.engine.target import WrappedTarget
from pants.python.python_requirement import PythonRequirement
from pants.testutil.test_base import TestBase


class PantsRequirementTest(TestBase):
    @classmethod
    def alias_groups(cls):
        return BuildFileAliases(
            objects={"python_requirement": PythonRequirement},
            context_aware_object_factories={PantsRequirement.alias: PantsRequirement},
        )

    @classmethod
    def target_types(cls):
        return [PythonRequirementLibrary]

    def assert_pants_requirement(
        self,
        build_file_entry: str,
        *,
        expected_target_name: str,
        expected_dist: str = "pantsbuild.pants",
        expected_module: str = "pants",
    ) -> None:
        self.add_to_build_file("3rdparty/python", f"{build_file_entry}\n")
        target = self.request_single_product(
            WrappedTarget, Address("3rdparty/python", expected_target_name)
        ).target
        assert isinstance(target, PythonRequirementLibrary)
        expected = PythonRequirement(
            f"{expected_dist}=={pants_version()}", modules=[expected_module]
        )
        requirements = target[PythonRequirementsField].value
        assert len(requirements) == 1
        req = requirements[0]
        assert req.requirement == expected.requirement
        assert req.modules == expected.modules

    def test_target_name(self) -> None:
        self.assert_pants_requirement("pants_requirement()", expected_target_name="python")
        self.assert_pants_requirement(
            "pants_requirement(name='pantsbuild.pants')", expected_target_name="pantsbuild.pants"
        )

    def test_dist(self) -> None:
        self.assert_pants_requirement(
            "pants_requirement(dist='pantsbuild.pants')", expected_target_name="pantsbuild.pants"
        )

    def test_contrib(self) -> None:
        dist = "pantsbuild.pants.contrib.bob"
        module = "pants.contrib.bob"
        self.assert_pants_requirement(
            f"pants_requirement(dist='{dist}')",
            expected_target_name=dist,
            expected_dist=dist,
            expected_module=module,
        )
        self.assert_pants_requirement(
            f"pants_requirement(name='bob', dist='{dist}')",
            expected_target_name="bob",
            expected_dist=dist,
            expected_module=module,
        )

    def test_bad_dist(self) -> None:
        with pytest.raises(ExecutionError):
            self.assert_pants_requirement(
                "pants_requirement(name='jane', dist='pantsbuild.pantsish')",
                expected_target_name="jane",
            )

    def test_modules_override(self) -> None:
        self.assert_pants_requirement(
            "pants_requirement(dist='pantsbuild.pants', modules=['fake'])",
            expected_target_name="pantsbuild.pants",
            expected_module="fake",
        )
