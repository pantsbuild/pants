# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pathlib import PurePath
from textwrap import dedent

import pytest

from pants.backend.project_info.list_roots import all_roots
from pants.backend.python.dependency_inference.module_mapper import (
    PythonModule,
    PythonModuleOwners,
    ThirdPartyModuleToAddressMapping,
)
from pants.backend.python.dependency_inference.module_mapper import rules as module_mapper_rules
from pants.backend.python.target_types import PythonLibrary, PythonRequirementLibrary
from pants.base.specs import AscendantAddresses
from pants.build_graph.build_file_aliases import BuildFileAliases
from pants.core.util_rules import strip_source_roots
from pants.engine.addresses import Address
from pants.engine.rules import RootRule
from pants.engine.selectors import Params
from pants.python.python_requirement import PythonRequirement
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


def test_module_possible_paths() -> None:
    assert set(PythonModule("typing").possible_stripped_paths()) == {
        PurePath("typing.py"),
        PurePath("typing") / "__init__.py",
    }
    assert set(PythonModule("typing.List").possible_stripped_paths()) == {
        PurePath("typing") / "List.py",
        PurePath("typing") / "List" / "__init__.py",
        PurePath("typing.py"),
        PurePath("typing") / "__init__.py",
    }


def test_module_address_spec() -> None:
    assert PythonModule("helloworld.app").address_spec(source_root=".") == AscendantAddresses(
        directory="helloworld/app"
    )
    assert PythonModule("helloworld.app").address_spec(
        source_root="src/python"
    ) == AscendantAddresses(directory="src/python/helloworld/app")


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
    def alias_groups(cls) -> BuildFileAliases:
        return BuildFileAliases(objects={"python_requirement": PythonRequirement})

    @classmethod
    def rules(cls):
        return (
            *super().rules(),
            *strip_source_roots.rules(),
            *module_mapper_rules(),
            all_roots,
            RootRule(PythonModule),
        )

    @classmethod
    def target_types(cls):
        return [PythonLibrary, PythonRequirementLibrary]

    def test_map_third_party_modules_to_targets(self) -> None:
        mapping = (
            "{'ansicolors': ['colors'], 'req1': ['mod1', 'mod2'], 'unused_req': ['unused'], "
            "'two_owners': ['two_owners']}"
        )
        options_bootstrapper = create_options_bootstrapper(
            args=[f"--python-setup-thirdparty-modules-mapping={mapping}"]
        )
        self.add_to_build_file(
            "3rdparty/python",
            dedent(
                """\
                python_requirement_library(
                  name='ansicolors',
                  requirements=[python_requirement('ansicolors==1.21')],
                )

                python_requirement_library(
                  name='req1',
                  requirements=[python_requirement('req1'), python_requirement('two_owners')],
                )

                python_requirement_library(
                  name='unknown_req',
                  requirements=[
                    python_requirement('unknown_req>3'),
                    python_requirement('two_owners'),
                  ],
                )
                """
            ),
        )
        result = self.request_single_product(
            ThirdPartyModuleToAddressMapping, options_bootstrapper
        ).mapping
        assert result == FrozenDict(
            {
                "colors": Address.parse("3rdparty/python:ansicolors"),
                "mod1": Address.parse("3rdparty/python:req1"),
                "mod2": Address.parse("3rdparty/python:req1"),
            }
        )

    def test_map_module_to_targets(self) -> None:
        options_bootstrapper = create_options_bootstrapper(
            args=[
                "--source-root-patterns=['source_root1', 'source_root2', '/']",
                "--python-setup-thirdparty-modules-mapping={'ansicolors': ['colors']}",
            ]
        )
        # First check that we can map 3rd-party modules.
        self.add_to_build_file(
            "3rdparty/python",
            dedent(
                """\
                python_requirement_library(
                  name='ansicolors',
                  requirements=[python_requirement('ansicolors==1.21')],
                )
                """
            ),
        )
        result = self.request_single_product(
            PythonModuleOwners, Params(PythonModule("colors.red"), options_bootstrapper)
        )
        assert result == PythonModuleOwners([Address.parse("3rdparty/python:ansicolors")])

        # We set up the same module in two source roots to confirm we properly handle source roots.
        # The first example uses a normal module path, whereas the second uses a package path.
        self.create_file("source_root1/project/app.py")
        self.add_to_build_file("source_root1/project", "python_library()")
        self.create_file("source_root2/project/app/__init__.py")
        self.add_to_build_file("source_root2/project/app", "python_library()")
        result = self.request_single_product(
            PythonModuleOwners, Params(PythonModule("project.app"), options_bootstrapper)
        )
        assert result == PythonModuleOwners(
            [Address.parse("source_root1/project"), Address.parse("source_root2/project/app")]
        )

        # Test a module with no owner (stdlib). This also sanity checks that we can handle when
        # there is no parent module.
        result = self.request_single_product(
            PythonModuleOwners, Params(PythonModule("typing"), options_bootstrapper)
        )
        assert not result

        # Test a module with a single owner with a top-level source root of ".". Also confirm we
        # can handle when the module includes a symbol (like a class name) at the end.
        self.create_file("script.py")
        self.add_to_build_file("", "python_library(name='script')")
        result = self.request_single_product(
            PythonModuleOwners, Params(PythonModule("script.Demo"), options_bootstrapper)
        )
        assert result == PythonModuleOwners([Address.parse("//:script")])
