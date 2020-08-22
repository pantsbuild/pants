# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pathlib import PurePath
from textwrap import dedent
from typing import Optional

import pytest

from pants.backend.python.dependency_inference.module_mapper import (
    FirstPartyModuleToAddressMapping,
    PythonModule,
    PythonModuleOwner,
    ThirdPartyModuleToAddressMapping,
    map_first_party_modules_to_addresses,
    map_module_to_address,
    map_third_party_modules_to_addresses,
)
from pants.backend.python.target_types import PythonLibrary, PythonRequirementLibrary
from pants.core.util_rules import source_files, stripped_source_files
from pants.engine.addresses import Address
from pants.engine.rules import RootRule
from pants.testutil.engine.util import Params
from pants.testutil.option.util import create_options_bootstrapper
from pants.testutil.test_base import TestBase
from pants.util.frozendict import FrozenDict


@pytest.mark.parametrize(
    "stripped_path,expected",
    [
        (PurePath("top_level.py"), "top_level"),
        (PurePath("dir", "subdir", "__init__.py"), "dir.subdir"),
        (PurePath("dir", "subdir", "app.py"), "dir.subdir.app"),
        (
            PurePath("src", "python", "project", "not_stripped.py"),
            "src.python.project.not_stripped",
        ),
    ],
)
def test_create_module_from_path(stripped_path: PurePath, expected: str) -> None:
    assert PythonModule.create_from_stripped_path(stripped_path) == PythonModule(expected)


def test_first_party_modules_mapping() -> None:
    util_addr = Address.parse("src/python/util:strutil")
    test_addr = Address.parse("tests/python/project_test:test")
    mapping = FirstPartyModuleToAddressMapping(
        FrozenDict({"util.strutil": util_addr, "project_test.test": test_addr})
    )
    assert mapping.address_for_module("util.strutil") == util_addr
    assert mapping.address_for_module("util.strutil.ensure_text") == util_addr
    assert mapping.address_for_module("util") is None
    assert mapping.address_for_module("project_test.test") == test_addr
    assert mapping.address_for_module("project_test.test.TestDemo") == test_addr
    assert mapping.address_for_module("project_test.test.TestDemo.method") is None
    assert mapping.address_for_module("project_test") is None
    assert mapping.address_for_module("project.test") is None


def test_third_party_modules_mapping() -> None:
    colors_addr = Address.parse("//:ansicolors")
    pants_addr = Address.parse("//:pantsbuild")
    mapping = ThirdPartyModuleToAddressMapping(
        FrozenDict({"colors": colors_addr, "pants": pants_addr})
    )
    assert mapping.address_for_module("colors") == colors_addr
    assert mapping.address_for_module("colors.red") == colors_addr
    assert mapping.address_for_module("pants") == pants_addr
    assert mapping.address_for_module("pants.task") == pants_addr
    assert mapping.address_for_module("pants.task.task") == pants_addr
    assert mapping.address_for_module("pants.task.task.Task") == pants_addr


class ModuleMapperTest(TestBase):
    @classmethod
    def rules(cls):
        return (
            *super().rules(),
            *stripped_source_files.rules(),
            *source_files.rules(),
            map_first_party_modules_to_addresses,
            map_module_to_address,
            map_third_party_modules_to_addresses,
            RootRule(PythonModule),
        )

    @classmethod
    def target_types(cls):
        return [PythonLibrary, PythonRequirementLibrary]

    def test_map_first_party_modules_to_addresses(self) -> None:
        options_bootstrapper = create_options_bootstrapper(
            args=["--source-root-patterns=['src/python', 'tests/python', 'build-support']"]
        )
        # Two modules belonging to the same target. We should generate subtargets for each file.
        self.create_files("src/python/project/util", ["dirutil.py", "tarutil.py"])
        self.add_to_build_file("src/python/project/util", "python_library()")
        # A module with two owners, meaning that neither should be resolved.
        self.create_file("src/python/two_owners.py")
        self.add_to_build_file("src/python", "python_library()")
        self.create_file("build-support/two_owners.py")
        self.add_to_build_file("build-support", "python_library()")
        # A package module. Because there's only one source file belonging to the target, we should
        # not generate subtargets.
        self.create_file("tests/python/project_test/demo_test/__init__.py")
        self.add_to_build_file("tests/python/project_test/demo_test", "python_library()")
        result = self.request_single_product(FirstPartyModuleToAddressMapping, options_bootstrapper)
        assert result.mapping == FrozenDict(
            {
                "project.util.dirutil": Address(
                    "src/python/project/util", relative_file_path="dirutil.py", target_name="util",
                ),
                "project.util.tarutil": Address(
                    "src/python/project/util", relative_file_path="tarutil.py", target_name="util",
                ),
                "project_test.demo_test": Address(
                    "tests/python/project_test/demo_test",
                    relative_file_path="__init__.py",
                    target_name="demo_test",
                ),
            }
        )

    def test_map_third_party_modules_to_addresses(self) -> None:
        self.add_to_build_file(
            "3rdparty/python",
            dedent(
                """\
                python_requirement_library(
                  name='ansicolors',
                  requirements=['ansicolors==1.21'],
                  module_mapping={'ansicolors': ['colors']},
                )

                python_requirement_library(
                  name='req1',
                  requirements=['req1', 'two_owners'],
                )

                python_requirement_library(
                  name='un_normalized',
                  requirements=['Un-Normalized-Project>3', 'two_owners'],
                )
                """
            ),
        )
        result = self.request_single_product(
            ThirdPartyModuleToAddressMapping, Params(create_options_bootstrapper())
        )
        assert result.mapping == FrozenDict(
            {
                "colors": Address.parse("3rdparty/python:ansicolors"),
                "req1": Address.parse("3rdparty/python:req1"),
                "un_normalized_project": Address.parse("3rdparty/python:un_normalized"),
            }
        )

    def test_map_module_to_address(self) -> None:
        options_bootstrapper = create_options_bootstrapper(
            args=["--source-root-patterns=['source_root1', 'source_root2', '/']"]
        )

        def get_owner(module: str) -> Optional[Address]:
            return self.request_single_product(
                PythonModuleOwner, Params(PythonModule(module), options_bootstrapper)
            ).address

        # First check that we can map 3rd-party modules.
        self.add_to_build_file(
            "3rdparty/python",
            dedent(
                """\
                python_requirement_library(
                  name='ansicolors',
                  requirements=['ansicolors==1.21'],
                  module_mapping={'ansicolors': ['colors']},
                )
                """
            ),
        )
        assert get_owner("colors.red") == Address.parse("3rdparty/python:ansicolors")

        # Check a first party module using a module path.
        self.create_file("source_root1/project/app.py")
        self.create_file("source_root1/project/file2.py")
        self.add_to_build_file("source_root1/project", "python_library()")
        assert get_owner("project.app") == Address(
            "source_root1/project", relative_file_path="app.py", target_name="project"
        )

        # Check a package path
        self.create_file("source_root2/project/subdir/__init__.py")
        self.add_to_build_file("source_root2/project/subdir", "python_library()")
        assert get_owner("project.subdir") == Address(
            "source_root2/project/subdir", relative_file_path="__init__.py", target_name="subdir",
        )

        # Test a module with no owner (stdlib). This also sanity checks that we can handle when
        # there is no parent module.
        assert get_owner("typing") is None

        # Test a module with a single owner with a top-level source root of ".". Also confirm we
        # can handle when the module includes a symbol (like a class name) at the end.
        self.create_file("script.py")
        self.add_to_build_file("", "python_library(name='script')")
        assert get_owner("script.Demo") == Address(
            "", relative_file_path="script.py", target_name="script"
        )
