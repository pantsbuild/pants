# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.python.register import build_file_aliases
from pants.backend.python.targets.python_requirement_library import PythonRequirementLibrary
from pants.base.build_environment import pants_version
from pants.build_graph.address_lookup_error import AddressLookupError
from pants.python.python_requirement import PythonRequirement
from pants.testutil.test_base import TestBase


class PantsRequirementTest(TestBase):
    @classmethod
    def alias_groups(cls):
        # NB: We use aliases and BUILD files to test proper registration of the pants_requirement macro.
        return build_file_aliases()

    def assert_pants_requirement(
        self, python_requirement_library, expected_dist="pantsbuild.pants"
    ):
        self.assertIsInstance(python_requirement_library, PythonRequirementLibrary)
        expected = PythonRequirement(f"{expected_dist}=={pants_version()}")

        def key(python_requirement):
            return (
                python_requirement.requirement.key,
                python_requirement.requirement.specs,
                python_requirement.requirement.extras,
            )

        self.assertEqual(
            [key(expected)], [key(pr) for pr in python_requirement_library.payload.requirements]
        )

    def test_default_name(self):
        self.add_to_build_file("3rdparty/python/pants", "pants_requirement()")

        python_requirement_library = self.target("3rdparty/python/pants")
        self.assert_pants_requirement(python_requirement_library)

    def test_custom_name(self):
        self.add_to_build_file("3rdparty/python/pants", "pants_requirement('pantsbuild.pants')")

        python_requirement_library = self.target("3rdparty/python/pants:pantsbuild.pants")
        self.assert_pants_requirement(python_requirement_library)

    def test_dist(self):
        self.add_to_build_file(
            "3rdparty/python/pants", "pants_requirement(dist='pantsbuild.pants')"
        )

        python_requirement_library = self.target("3rdparty/python/pants:pantsbuild.pants")
        self.assert_pants_requirement(python_requirement_library)

    def test_contrib(self):
        self.add_to_build_file(
            "3rdparty/python/pants", "pants_requirement(dist='pantsbuild.pants.contrib.bob')"
        )

        python_requirement_library = self.target(
            "3rdparty/python/pants:pantsbuild.pants.contrib.bob"
        )
        self.assert_pants_requirement(
            python_requirement_library, expected_dist="pantsbuild.pants.contrib.bob"
        )

    def test_custom_name_contrib(self):
        self.add_to_build_file(
            "3rdparty/python/pants",
            "pants_requirement(name='bob', dist='pantsbuild.pants.contrib.bob')",
        )

        python_requirement_library = self.target("3rdparty/python/pants:bob")
        self.assert_pants_requirement(
            python_requirement_library, expected_dist="pantsbuild.pants.contrib.bob"
        )

    def test_bad_dist(self):
        self.add_to_build_file(
            "3rdparty/python/pants", "pants_requirement(name='jane', dist='pantsbuild.pantsish')"
        )

        with self.assertRaises(AddressLookupError):
            # The pants_requirement should raise on the invalid dist name of pantsbuild.pantsish making
            # the target at 3rdparty/python/pants:jane fail to exist.
            self.target("3rdparty/python/pants:jane")
