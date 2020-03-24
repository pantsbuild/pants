# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from textwrap import dedent

from pants.backend.python.targets.import_wheels_mixin import ImportWheelsMixin
from pants.backend.python.targets.python_requirement_library import PythonRequirementLibrary
from pants.backend.python.targets.unpacked_whls import UnpackedWheels
from pants.build_graph.build_file_aliases import BuildFileAliases
from pants.python.python_requirement import PythonRequirement
from pants.testutil.test_base import TestBase
from pants.util.collections import assert_single_element


class UnpackedWheelsTest(TestBase):
    @classmethod
    def alias_groups(cls):
        return BuildFileAliases(
            targets={
                "python_requirement_library": PythonRequirementLibrary,
                "unpacked_whls": UnpackedWheels,
            },
            objects={"python_requirement": PythonRequirement},
        )

    def test_empty_libraries(self):
        with self.assertRaises(UnpackedWheels.ExpectedLibrariesError):
            self.make_target(":foo", UnpackedWheels, module_name="foo")

    def test_simple(self):
        self.make_target(
            ":import_whls", PythonRequirementLibrary, requirements=[PythonRequirement("foo==123")]
        )
        target = self.make_target(
            ":foo", UnpackedWheels, libraries=[":import_whls"], module_name="foo"
        )

        self.assertIsInstance(target, UnpackedWheels)
        dependency_specs = [
            spec for spec in target.compute_dependency_address_specs(payload=target.payload)
        ]
        self.assertSequenceEqual([":import_whls"], dependency_specs)
        import_whl_dep = assert_single_element(target.all_imported_requirements)
        self.assertIsInstance(import_whl_dep, PythonRequirement)

    def test_bad_libraries_ref(self):
        self.make_target(
            ":right-type", PythonRequirementLibrary, requirements=[PythonRequirement("foo==123")]
        )
        # Making a target which is not a requirement library, which causes an error.
        self.make_target(
            ":wrong-type", UnpackedWheels, libraries=[":right-type"], module_name="foo"
        )
        target = self.make_target(
            ":foo", UnpackedWheels, libraries=[":wrong-type"], module_name="foo"
        )
        with self.assertRaises(ImportWheelsMixin.WrongTargetTypeError):
            target.imported_targets

    def test_has_all_imported_req_libs(self):
        def assert_dep(reqA, reqB):
            self.assertEqual(reqA.requirement, reqB.requirement)

        def sort_requirements(reqs):
            return list(sorted(reqs, key=lambda r: str(r.requirement)))

        self.add_to_build_file(
            "BUILD",
            dedent(
                """
                python_requirement_library(name='lib1',
                  requirements=[
                    python_requirement('testName1==123'),
                  ],
                )
                python_requirement_library(name='lib2',
                  requirements=[
                    python_requirement('testName2==456'),
                    python_requirement('testName3==789'),
                  ],
                )
                unpacked_whls(name='unpacked-lib',
                  libraries=[':lib1', ':lib2'],
                  module_name='foo',
                )
                """
            ),
        )
        lib1 = self.target("//:lib1")
        self.assertIsInstance(lib1, PythonRequirementLibrary)
        assert_dep(assert_single_element(lib1.requirements), PythonRequirement("testName1==123"))

        lib2 = self.target("//:lib2")
        self.assertIsInstance(lib2, PythonRequirementLibrary)
        lib2_reqs = sort_requirements(lib2.requirements)
        self.assertEqual(2, len(lib2_reqs))
        assert_dep(lib2_reqs[0], PythonRequirement("testName2==456"))
        assert_dep(lib2_reqs[1], PythonRequirement("testName3==789"))

        unpacked_lib = self.target("//:unpacked-lib")
        unpacked_req_libs = sort_requirements(unpacked_lib.all_imported_requirements)

        self.assertEqual(3, len(unpacked_req_libs))
        assert_dep(unpacked_req_libs[0], PythonRequirement("testName1==123"))
        assert_dep(unpacked_req_libs[1], PythonRequirement("testName2==456"))
        assert_dep(unpacked_req_libs[2], PythonRequirement("testName3==789"))
