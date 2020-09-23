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
)
from pants.backend.python.dependency_inference.module_mapper import rules as module_mapper_rules
from pants.backend.python.target_types import PythonLibrary, PythonRequirementLibrary
from pants.core.util_rules import stripped_source_files
from pants.engine.addresses import Address
from pants.testutil.option_util import create_options_bootstrapper
from pants.testutil.rule_runner import QueryRule, RuleRunner
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


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *stripped_source_files.rules(),
            *module_mapper_rules(),
            QueryRule(FirstPartyModuleToAddressMapping, ()),
            QueryRule(ThirdPartyModuleToAddressMapping, ()),
            QueryRule(PythonModuleOwner, (PythonModule,)),
        ],
        target_types=[PythonLibrary, PythonRequirementLibrary],
    )


def test_map_first_party_modules_to_addresses(rule_runner: RuleRunner) -> None:
    options_bootstrapper = create_options_bootstrapper(
        args=["--source-root-patterns=['src/python', 'tests/python', 'build-support']"]
    )
    # Two modules belonging to the same target. We should generate subtargets for each file.
    rule_runner.create_files("src/python/project/util", ["dirutil.py", "tarutil.py"])
    rule_runner.add_to_build_file("src/python/project/util", "python_library()")
    # A module with two owners, meaning that neither should be resolved.
    rule_runner.create_file("src/python/two_owners.py")
    rule_runner.add_to_build_file("src/python", "python_library()")
    rule_runner.create_file("build-support/two_owners.py")
    rule_runner.add_to_build_file("build-support", "python_library()")
    # A package module. Because there's only one source file belonging to the target, we should
    # not generate subtargets.
    rule_runner.create_file("tests/python/project_test/demo_test/__init__.py")
    rule_runner.add_to_build_file("tests/python/project_test/demo_test", "python_library()")
    result = rule_runner.request(FirstPartyModuleToAddressMapping, [options_bootstrapper])
    assert result.mapping == FrozenDict(
        {
            "project.util.dirutil": Address(
                "src/python/project/util",
                relative_file_path="dirutil.py",
                target_name="util",
            ),
            "project.util.tarutil": Address(
                "src/python/project/util",
                relative_file_path="tarutil.py",
                target_name="util",
            ),
            "project_test.demo_test": Address(
                "tests/python/project_test/demo_test",
                relative_file_path="__init__.py",
                target_name="demo_test",
            ),
        }
    )


def test_map_third_party_modules_to_addresses(rule_runner: RuleRunner) -> None:
    rule_runner.add_to_build_file(
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

            python_requirement_library(
              name='direct_references',
              requirements=[
                'pip@ git+https://github.com/pypa/pip.git', 'local_dist@ file:///path/to/dist.whl',
              ],
            )
            """
        ),
    )
    result = rule_runner.request(ThirdPartyModuleToAddressMapping, [create_options_bootstrapper()])
    assert result.mapping == FrozenDict(
        {
            "colors": Address("3rdparty/python", target_name="ansicolors"),
            "local_dist": Address("3rdparty/python", target_name="direct_references"),
            "pip": Address("3rdparty/python", target_name="direct_references"),
            "req1": Address("3rdparty/python", target_name="req1"),
            "un_normalized_project": Address("3rdparty/python", target_name="un_normalized"),
        }
    )


def test_map_module_to_address(rule_runner: RuleRunner) -> None:
    options_bootstrapper = create_options_bootstrapper(
        args=["--source-root-patterns=['source_root1', 'source_root2', '/']"]
    )

    def get_owner(module: str) -> Optional[Address]:
        return rule_runner.request(
            PythonModuleOwner, [PythonModule(module), options_bootstrapper]
        ).address

    # First check that we can map 3rd-party modules.
    rule_runner.add_to_build_file(
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
    rule_runner.create_file("source_root1/project/app.py")
    rule_runner.create_file("source_root1/project/file2.py")
    rule_runner.add_to_build_file("source_root1/project", "python_library()")
    assert get_owner("project.app") == Address(
        "source_root1/project", relative_file_path="app.py", target_name="project"
    )

    # Check a package path
    rule_runner.create_file("source_root2/project/subdir/__init__.py")
    rule_runner.add_to_build_file("source_root2/project/subdir", "python_library()")
    assert get_owner("project.subdir") == Address(
        "source_root2/project/subdir",
        relative_file_path="__init__.py",
        target_name="subdir",
    )

    # Test a module with no owner (stdlib). This also sanity checks that we can handle when
    # there is no parent module.
    assert get_owner("typing") is None

    # Test a module with a single owner with a top-level source root of ".". Also confirm we
    # can handle when the module includes a symbol (like a class name) at the end.
    rule_runner.create_file("script.py")
    rule_runner.add_to_build_file("", "python_library(name='script')")
    assert get_owner("script.Demo") == Address(
        "", relative_file_path="script.py", target_name="script"
    )
