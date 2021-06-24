# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from pathlib import Path, PurePath
from textwrap import dedent

import pytest
from packaging.utils import canonicalize_name as canonicalize_project_name

from pants.backend.codegen.protobuf.python import python_protobuf_module_mapper
from pants.backend.codegen.protobuf.target_types import ProtobufLibrary
from pants.backend.python.dependency_inference.default_module_mapping import DEFAULT_MODULE_MAPPING
from pants.backend.python.dependency_inference.module_mapper import (
    FirstPartyPythonModuleMapping,
    PythonModule,
    PythonModuleOwners,
    ThirdPartyPythonModuleMapping,
)
from pants.backend.python.dependency_inference.module_mapper import rules as module_mapper_rules
from pants.backend.python.target_types import PythonLibrary, PythonRequirementLibrary
from pants.core.util_rules import stripped_source_files
from pants.engine.addresses import Address
from pants.testutil.rule_runner import QueryRule, RuleRunner
from pants.util.frozendict import FrozenDict


def test_default_module_mapping_is_normalized() -> None:
    for k in DEFAULT_MODULE_MAPPING:
        assert k == canonicalize_project_name(
            k
        ), "Please update `DEFAULT_MODULE_MAPPING` to use canonical project names"


@pytest.mark.parametrize(
    "stripped_path,expected",
    [
        ("top_level.py", "top_level"),
        ("dir/subdir/__init__.py", "dir.subdir"),
        ("dir/subdir/app.py", "dir.subdir.app"),
        ("src/python/project/not_stripped.py", "src.python.project.not_stripped"),
    ],
)
def test_create_module_from_path(stripped_path: str, expected: str) -> None:
    assert PythonModule.create_from_stripped_path(PurePath(stripped_path)) == PythonModule(expected)


def test_first_party_modules_mapping() -> None:
    root_addr = Address("", relative_file_path="root.py")
    util_addr = Address("src/python/util", relative_file_path="strutil.py")
    util_stubs_addr = Address("src/python/util", relative_file_path="strutil.pyi")
    test_addr = Address("tests/python/project_test", relative_file_path="test.py")
    mapping = FirstPartyPythonModuleMapping(
        mapping=FrozenDict(
            {
                "root": (root_addr,),
                "util.strutil": (util_addr, util_stubs_addr),
                "project_test.test": (test_addr,),
            }
        ),
        ambiguous_modules=FrozenDict(
            {"ambiguous": (root_addr, util_addr), "util.ambiguous": (util_addr, test_addr)}
        ),
    )

    def assert_addresses(
        mod: str, expected: tuple[tuple[Address, ...], tuple[Address, ...]]
    ) -> None:
        assert mapping.addresses_for_module(mod) == expected

    unknown = ((), ())

    root = ((root_addr,), ())
    assert_addresses("root", root)
    assert_addresses("root.func", root)
    assert_addresses("root.submodule.func", unknown)

    util = ((util_addr, util_stubs_addr), ())
    assert_addresses("util.strutil", util)
    assert_addresses("util.strutil.ensure_text", util)
    assert_addresses("util", unknown)

    test = ((test_addr,), ())
    assert_addresses("project_test.test", test)
    assert_addresses("project_test.test.TestDemo", test)
    assert_addresses("project_test", unknown)
    assert_addresses("project.test", unknown)

    ambiguous = ((), (root_addr, util_addr))
    assert_addresses("ambiguous", ambiguous)
    assert_addresses("ambiguous.func", ambiguous)
    assert_addresses("ambiguous.submodule.func", unknown)

    util_ambiguous = ((), (util_addr, test_addr))
    assert_addresses("util.ambiguous", util_ambiguous)
    assert_addresses("util.ambiguous.Foo", util_ambiguous)
    assert_addresses("util.ambiguous.Foo.method", unknown)


def test_third_party_modules_mapping() -> None:
    colors_addr = Address("", target_name="ansicolors")
    pants_addr = Address("", target_name="pantsbuild")
    pants_testutil_addr = Address("", target_name="pantsbuild.testutil")
    submodule_addr = Address("", target_name="submodule")
    mapping = ThirdPartyPythonModuleMapping(
        mapping=FrozenDict(
            {
                "colors": colors_addr,
                "pants": pants_addr,
                "req.submodule": submodule_addr,
                "pants.testutil": pants_testutil_addr,
            }
        ),
        ambiguous_modules=FrozenDict({"ambiguous": (colors_addr, pants_addr)}),
    )

    def assert_addresses(mod: str, expected: tuple[Address | None, tuple[Address, ...]]) -> None:
        assert mapping.address_for_module(mod) == expected

    unknown = (None, ())

    colors = (colors_addr, ())
    assert_addresses("colors", colors)
    assert_addresses("colors.red", colors)

    pants = (pants_addr, ())
    assert_addresses("pants", pants)
    assert_addresses("pants.task", pants)
    assert_addresses("pants.task.task", pants)
    assert_addresses("pants.task.task.Task", pants)

    testutil = (pants_testutil_addr, ())
    assert_addresses("pants.testutil", testutil)
    assert_addresses("pants.testutil.foo", testutil)

    submodule = (submodule_addr, ())
    assert_addresses("req.submodule", submodule)
    assert_addresses("req.submodule.foo", submodule)
    assert_addresses("req.another", unknown)
    assert_addresses("req", unknown)

    assert_addresses("unknown", unknown)
    assert_addresses("unknown.pants", unknown)

    ambiguous = (None, (colors_addr, pants_addr))
    assert_addresses("ambiguous", ambiguous)
    assert_addresses("ambiguous.foo", ambiguous)
    assert_addresses("ambiguous.foo.bar", ambiguous)


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *stripped_source_files.rules(),
            *module_mapper_rules(),
            *python_protobuf_module_mapper.rules(),
            QueryRule(FirstPartyPythonModuleMapping, []),
            QueryRule(ThirdPartyPythonModuleMapping, []),
            QueryRule(PythonModuleOwners, [PythonModule]),
        ],
        target_types=[PythonLibrary, PythonRequirementLibrary, ProtobufLibrary],
    )


def test_map_first_party_modules_to_addresses(rule_runner: RuleRunner) -> None:
    rule_runner.set_options(
        ["--source-root-patterns=['src/python', 'tests/python', 'build-support']"]
    )
    rule_runner.write_files(
        {
            "src/python/project/util/dirutil.py": "",
            "src/python/project/util/tarutil.py": "",
            "src/python/project/util/BUILD": "python_library()",
            # A module with two owners, meaning that neither should be resolved.
            "src/python/two_owners.py": "",
            "src/python/BUILD": "python_library()",
            "build-support/two_owners.py": "",
            "build-support/BUILD": "python_library()",
            # A module with two owners that are type stubs.
            "src/python/stub_ambiguity/f.pyi": "",
            "src/python/stub_ambiguity/BUILD": "python_library()",
            "build-support/stub_ambiguity/f.pyi": "",
            "build-support/stub_ambiguity/BUILD": "python_library()",
            # A package module.
            "tests/python/project_test/demo_test/__init__.py": "",
            "tests/python/project_test/demo_test/BUILD": "python_library()",
            # A module with both an implementation and a type stub. Even though the module is the
            # same, we special-case it to be legal for both file targets to be inferred.
            "src/python/stubs/stub.py": "",
            "src/python/stubs/stub.pyi": "",
            "src/python/stubs/BUILD": "python_library()",
            # Check that plugin mappings work. Note that we duplicate one of the files with a normal
            # python_library(), which means neither the Protobuf nor Python targets should be used.
            "src/python/protos/f1.proto": "",
            "src/python/protos/f2.proto": "",
            "src/python/protos/f2_pb2.py": "",
            "src/python/protos/BUILD": dedent(
                """\
                protobuf_library(name='protos')
                python_library(name='py')
                """
            ),
            # If a module is ambiguous within a particular implementation, which means that it's
            # not used in that implementation's final mapping, it should still trigger ambiguity
            # with another implementation. Here, we have ambiguity with the Protobuf targets, but
            # the Python file has no ambiguity with other Python files; the Protobuf ambiguity
            # needs to result in Python being ambiguous.
            "src/python/protos_ambiguous/f.proto": "",
            "src/python/protos_ambiguous/f_pb2.py": "",
            "src/python/protos_ambiguous/BUILD": dedent(
                """\
                protobuf_library(name='protos1')
                protobuf_library(name='protos2')
                python_library(name='py')
                """
            ),
        }
    )

    result = rule_runner.request(FirstPartyPythonModuleMapping, [])
    assert result == FirstPartyPythonModuleMapping(
        mapping=FrozenDict(
            {
                "project.util.dirutil": (
                    Address("src/python/project/util", relative_file_path="dirutil.py"),
                ),
                "project.util.tarutil": (
                    Address("src/python/project/util", relative_file_path="tarutil.py"),
                ),
                "project_test.demo_test": (
                    Address(
                        "tests/python/project_test/demo_test", relative_file_path="__init__.py"
                    ),
                ),
                "protos.f1_pb2": (
                    Address(
                        "src/python/protos", relative_file_path="f1.proto", target_name="protos"
                    ),
                ),
                "stubs.stub": (
                    Address("src/python/stubs", relative_file_path="stub.py"),
                    Address("src/python/stubs", relative_file_path="stub.pyi"),
                ),
            }
        ),
        ambiguous_modules=FrozenDict(
            {
                "protos.f2_pb2": (
                    Address(
                        "src/python/protos", relative_file_path="f2.proto", target_name="protos"
                    ),
                    Address("src/python/protos", relative_file_path="f2_pb2.py", target_name="py"),
                ),
                "protos_ambiguous.f_pb2": (
                    Address(
                        "src/python/protos_ambiguous",
                        relative_file_path="f.proto",
                        target_name="protos1",
                    ),
                    Address(
                        "src/python/protos_ambiguous",
                        relative_file_path="f.proto",
                        target_name="protos2",
                    ),
                    Address(
                        "src/python/protos_ambiguous",
                        relative_file_path="f_pb2.py",
                        target_name="py",
                    ),
                ),
                "stub_ambiguity.f": (
                    Address("build-support/stub_ambiguity", relative_file_path="f.pyi"),
                    Address("src/python/stub_ambiguity", relative_file_path="f.pyi"),
                ),
                "two_owners": (
                    Address("build-support", relative_file_path="two_owners.py"),
                    Address("src/python", relative_file_path="two_owners.py"),
                ),
            }
        ),
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
              requirements=['Un-Normalized-Project>3', 'two_owners', 'DiFFerent-than_Mapping'],
              module_mapping={"different_THAN-mapping": ["different_than_mapping"]},
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
    result = rule_runner.request(ThirdPartyPythonModuleMapping, [])
    assert result == ThirdPartyPythonModuleMapping(
        mapping=FrozenDict(
            {
                "colors": Address("3rdparty/python", target_name="ansicolors"),
                "different_than_mapping": Address("3rdparty/python", target_name="un_normalized"),
                "local_dist": Address("3rdparty/python", target_name="direct_references"),
                "pip": Address("3rdparty/python", target_name="direct_references"),
                "req1": Address("3rdparty/python", target_name="req1"),
                "un_normalized_project": Address("3rdparty/python", target_name="un_normalized"),
            }
        ),
        ambiguous_modules=FrozenDict(
            {
                "two_owners": (
                    Address("3rdparty/python", target_name="req1"),
                    Address("3rdparty/python", target_name="un_normalized"),
                ),
            }
        ),
    )


def test_map_module_to_address(rule_runner: RuleRunner) -> None:
    rule_runner.set_options(["--source-root-patterns=['source_root1', 'source_root2', '/']"])

    def assert_owners(
        module: str, *, expected: list[Address], expected_ambiguous: list[Address] | None = None
    ) -> None:
        owners = rule_runner.request(PythonModuleOwners, [PythonModule(module)])
        assert list(owners.unambiguous) == expected
        assert list(owners.ambiguous) == (expected_ambiguous or [])

    # First check that we can map 3rd-party modules without ambiguity.
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
    assert_owners("colors.red", expected=[Address("3rdparty/python", target_name="ansicolors")])

    # Now test that we can handle first-party type stubs that go along with that third party
    # requirement. Note that `colors.pyi` is at the top-level of the source root so that it strips
    # to the module `colors`.
    rule_runner.create_file("source_root1/colors.pyi")
    rule_runner.add_to_build_file("source_root1", "python_library()")
    assert_owners(
        "colors.red",
        expected=[
            Address("3rdparty/python", target_name="ansicolors"),
            Address("source_root1", relative_file_path="colors.pyi"),
        ],
    )

    # But don't allow a first-party implementation with the same module name.
    Path(rule_runner.build_root, "source_root1/colors.pyi").unlink()
    rule_runner.create_file("source_root1/colors.py")
    assert_owners(
        "colors.red",
        expected=[],
        expected_ambiguous=[
            Address("3rdparty/python", target_name="ansicolors"),
            Address("source_root1", relative_file_path="colors.py"),
        ],
    )

    # Check a first party module using a module path.
    rule_runner.create_file("source_root1/project/app.py")
    rule_runner.create_file("source_root1/project/file2.py")
    rule_runner.add_to_build_file("source_root1/project", "python_library()")
    assert_owners(
        "project.app", expected=[Address("source_root1/project", relative_file_path="app.py")]
    )

    # Now check with a type stub.
    rule_runner.create_file("source_root1/project/app.pyi")
    assert_owners(
        "project.app",
        expected=[
            Address("source_root1/project", relative_file_path="app.py"),
            Address("source_root1/project", relative_file_path="app.pyi"),
        ],
    )

    # Check a package path
    rule_runner.create_file("source_root2/project/subdir/__init__.py")
    rule_runner.add_to_build_file("source_root2/project/subdir", "python_library()")
    assert_owners(
        "project.subdir",
        expected=[Address("source_root2/project/subdir", relative_file_path="__init__.py")],
    )

    # Test a module with no owner (stdlib). This also smoke tests that we can handle when
    # there is no parent module.
    assert_owners("typing", expected=[])

    # Test a module with a single owner with a top-level source root of ".". Also confirm we
    # can handle when the module includes a symbol (like a class name) at the end.
    rule_runner.create_file("script.py")
    rule_runner.add_to_build_file("", "python_library(name='script')")
    assert_owners(
        "script.Demo", expected=[Address("", relative_file_path="script.py", target_name="script")]
    )

    # Ambiguous modules should be recorded.
    rule_runner.create_files("source_root1/ambiguous", ["f1.py", "f2.py", "f3.py"])
    rule_runner.add_to_build_file(
        "source_root1/ambiguous",
        dedent(
            """\
            # Ambiguity purely within third-party deps.
            python_requirement_library(name='thirdparty1', requirements=['foo'])
            python_requirement_library(name='thirdparty2', requirements=['foo'])

            # Ambiguity purely within first-party deps.
            python_library(name="firstparty1", sources=["f1.py"])
            python_library(name="firstparty2", sources=["f1.py"])

            # Ambiguity within third-party, which should result in ambiguity for first-party too.
            # These all share the module `ambiguous.f2`.
            python_requirement_library(
                name='thirdparty3', requirements=['bar'], module_mapping={'bar': ['ambiguous.f2']}
            )
            python_requirement_library(
                name='thirdparty4', requirements=['bar'], module_mapping={'bar': ['ambiguous.f2']}
            )
            python_library(name="firstparty3", sources=["f2.py"])

            # Ambiguity within first-party, which should result in ambiguity for third-party too.
            # These all share the module `ambiguous.f3`.
            python_library(name="firstparty4", sources=["f3.py"])
            python_library(name="firstparty5", sources=["f3.py"])
            python_requirement_library(
                name='thirdparty5', requirements=['baz'], module_mapping={'baz': ['ambiguous.f3']}
            )
            """
        ),
    )
    assert_owners(
        "foo",
        expected=[],
        expected_ambiguous=[
            Address("source_root1/ambiguous", target_name="thirdparty1"),
            Address("source_root1/ambiguous", target_name="thirdparty2"),
        ],
    )
    assert_owners(
        "ambiguous.f1",
        expected=[],
        expected_ambiguous=[
            Address(
                "source_root1/ambiguous", relative_file_path="f1.py", target_name="firstparty1"
            ),
            Address(
                "source_root1/ambiguous", relative_file_path="f1.py", target_name="firstparty2"
            ),
        ],
    )
    assert_owners(
        "ambiguous.f2",
        expected=[],
        expected_ambiguous=[
            Address("source_root1/ambiguous", target_name="thirdparty3"),
            Address("source_root1/ambiguous", target_name="thirdparty4"),
            Address(
                "source_root1/ambiguous", relative_file_path="f2.py", target_name="firstparty3"
            ),
        ],
    )
    assert_owners(
        "ambiguous.f3",
        expected=[],
        expected_ambiguous=[
            Address("source_root1/ambiguous", target_name="thirdparty5"),
            Address(
                "source_root1/ambiguous", relative_file_path="f3.py", target_name="firstparty4"
            ),
            Address(
                "source_root1/ambiguous", relative_file_path="f3.py", target_name="firstparty5"
            ),
        ],
    )
