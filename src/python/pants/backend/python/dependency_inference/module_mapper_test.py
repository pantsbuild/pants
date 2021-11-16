# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from pathlib import PurePath
from textwrap import dedent

import pytest
from packaging.utils import canonicalize_name as canonicalize_project_name

from pants.backend.codegen.protobuf.python import python_protobuf_module_mapper
from pants.backend.codegen.protobuf.target_types import ProtobufSourcesGeneratorTarget
from pants.backend.codegen.protobuf.target_types import rules as protobuf_target_type_rules
from pants.backend.python import target_types_rules
from pants.backend.python.dependency_inference.default_module_mapping import (
    DEFAULT_MODULE_MAPPING,
    DEFAULT_TYPE_STUB_MODULE_MAPPING,
)
from pants.backend.python.dependency_inference.module_mapper import (
    FirstPartyPythonModuleMapping,
    PythonModule,
    PythonModuleOwners,
    ThirdPartyPythonModuleMapping,
)
from pants.backend.python.dependency_inference.module_mapper import rules as module_mapper_rules
from pants.backend.python.target_types import (
    PythonRequirementTarget,
    PythonSourcesGeneratorTarget,
    PythonSourceTarget,
)
from pants.core.util_rules import stripped_source_files
from pants.engine.addresses import Address
from pants.testutil.rule_runner import QueryRule, RuleRunner
from pants.util.frozendict import FrozenDict
from pants.util.ordered_set import FrozenOrderedSet


def test_default_module_mapping_is_normalized() -> None:
    for k in DEFAULT_MODULE_MAPPING:
        assert k == canonicalize_project_name(
            k
        ), "Please update `DEFAULT_MODULE_MAPPING` to use canonical project names"
    for k in DEFAULT_TYPE_STUB_MODULE_MAPPING:
        assert k == canonicalize_project_name(
            k
        ), "Please update `DEFAULT_TYPE_STUB_MODULE_MAPPING` to use canonical project names"


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
    colors_stubs_addr = Address("", target_name="types-ansicolors")
    pants_addr = Address("", target_name="pantsbuild")
    pants_testutil_addr = Address("", target_name="pantsbuild.testutil")
    submodule_addr = Address("", target_name="submodule")
    mapping = ThirdPartyPythonModuleMapping(
        mapping=FrozenDict(
            {
                "colors": (colors_addr, colors_stubs_addr),
                "pants": (pants_addr,),
                "req.submodule": (submodule_addr,),
                "pants.testutil": (pants_testutil_addr,),
            }
        ),
        ambiguous_modules=FrozenDict({"ambiguous": (colors_addr, pants_addr)}),
    )

    def assert_addresses(
        mod: str, expected: tuple[tuple[Address, ...], tuple[Address, ...]]
    ) -> None:
        assert mapping.addresses_for_module(mod) == expected

    unknown = ((), ())

    colors = ((colors_addr, colors_stubs_addr), ())
    assert_addresses("colors", colors)
    assert_addresses("colors.red", colors)

    pants = ((pants_addr,), ())
    assert_addresses("pants", pants)
    assert_addresses("pants.task", pants)
    assert_addresses("pants.task.task", pants)
    assert_addresses("pants.task.task.Task", pants)

    testutil = ((pants_testutil_addr,), ())
    assert_addresses("pants.testutil", testutil)
    assert_addresses("pants.testutil.foo", testutil)

    submodule = ((submodule_addr,), ())
    assert_addresses("req.submodule", submodule)
    assert_addresses("req.submodule.foo", submodule)
    assert_addresses("req.another", unknown)
    assert_addresses("req", unknown)

    assert_addresses("unknown", unknown)
    assert_addresses("unknown.pants", unknown)

    ambiguous = ((), (colors_addr, pants_addr))
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
            *target_types_rules.rules(),
            *protobuf_target_type_rules(),
            QueryRule(FirstPartyPythonModuleMapping, []),
            QueryRule(ThirdPartyPythonModuleMapping, []),
            QueryRule(PythonModuleOwners, [PythonModule]),
        ],
        target_types=[
            PythonSourceTarget,
            PythonSourcesGeneratorTarget,
            PythonRequirementTarget,
            ProtobufSourcesGeneratorTarget,
        ],
    )


def test_map_first_party_modules_to_addresses(rule_runner: RuleRunner) -> None:
    rule_runner.set_options(
        ["--source-root-patterns=['src/python', 'tests/python', 'build-support']"]
    )
    rule_runner.write_files(
        {
            "src/python/project/util/dirutil.py": "",
            "src/python/project/util/tarutil.py": "",
            "src/python/project/util/BUILD": "python_sources()",
            # A module with two owners, meaning that neither should be resolved.
            "src/python/two_owners.py": "",
            "src/python/BUILD": "python_sources()",
            "build-support/two_owners.py": "",
            "build-support/BUILD": "python_sources()",
            # A module with two owners that are type stubs.
            "src/python/stub_ambiguity/f.pyi": "",
            "src/python/stub_ambiguity/BUILD": "python_sources()",
            "build-support/stub_ambiguity/f.pyi": "",
            "build-support/stub_ambiguity/BUILD": "python_sources()",
            # A package module.
            "tests/python/project_test/demo_test/__init__.py": "",
            "tests/python/project_test/demo_test/BUILD": "python_sources()",
            # A module with both an implementation and a type stub. Even though the module is the
            # same, we special-case it to be legal for both file targets to be inferred.
            "src/python/stubs/stub.py": "",
            "src/python/stubs/stub.pyi": "",
            "src/python/stubs/BUILD": "python_sources()",
            # Check that plugin mappings work. Note that we duplicate one of the files with a normal
            # python_source, which means neither the Protobuf nor Python targets should be used.
            "src/python/protos/f1.proto": "",
            "src/python/protos/f2.proto": "",
            "src/python/protos/f2_pb2.py": "",
            "src/python/protos/BUILD": dedent(
                """\
                protobuf_sources(name='protos')
                python_source(name='py', source="f2_pb2.py")
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
                protobuf_sources(name='protos1')
                protobuf_sources(name='protos2')
                python_source(name='py', source="f_pb2.py")
                """
            ),
        }
    )

    result = rule_runner.request(FirstPartyPythonModuleMapping, [])
    assert result.mapping == FrozenDict(
        {
            "project.util.dirutil": (
                Address("src/python/project/util", relative_file_path="dirutil.py"),
            ),
            "project.util.tarutil": (
                Address("src/python/project/util", relative_file_path="tarutil.py"),
            ),
            "project_test.demo_test": (
                Address("tests/python/project_test/demo_test", relative_file_path="__init__.py"),
            ),
            "protos.f1_pb2": (
                Address("src/python/protos", relative_file_path="f1.proto", target_name="protos"),
            ),
            "stubs.stub": (
                Address("src/python/stubs", relative_file_path="stub.py"),
                Address("src/python/stubs", relative_file_path="stub.pyi"),
            ),
        }
    )
    assert result.ambiguous_modules == FrozenDict(
        {
            "protos.f2_pb2": (
                Address("src/python/protos", target_name="py"),
                Address("src/python/protos", relative_file_path="f2.proto", target_name="protos"),
            ),
            "protos_ambiguous.f_pb2": (
                Address("src/python/protos_ambiguous", target_name="py"),
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
    )
    assert result.modules_with_type_stub == FrozenOrderedSet(["stubs.stub"])


def test_map_third_party_modules_to_addresses(rule_runner: RuleRunner) -> None:
    def req(
        tgt_name: str,
        req_str: str,
        *,
        modules: list[str] | None = None,
        stub_modules: list[str] | None = None,
        module_mapping: dict[str, list[str]] | None = None,
    ) -> str:
        return (
            f"python_requirement(name='{tgt_name}', requirements=['{req_str}'], "
            f"modules={modules or []},"
            f"type_stub_modules={stub_modules or []},"
            f"module_mapping={repr(module_mapping or {})})"
        )

    build_file = "\n\n".join(
        [
            req("req1", "req1==1.2"),
            req("un_normalized", "Un-Normalized-Project>3"),
            req("file_dist", "file_dist@ file:///path/to/dist.whl"),
            req("vcs_dist", "vcs_dist@ git+https://github.com/vcs/dist.git"),
            req("modules", "foo==1", modules=["mapped_module"]),
            req(
                "module_mapping_un_normalized",
                "DiFFerent-than_Mapping",
                module_mapping={"different_THAN-mapping": ["module_mapping_un_normalized"]},
            ),
            # We extract the module from type stub dependencies.
            req("typed-dep1", "typed-dep1-types"),
            req("typed-dep2", "types-typed-dep2"),
            req("typed-dep3", "typed-dep3-stubs"),
            req("typed-dep4", "stubs-typed-dep4"),
            req("typed-dep5", "typed-dep5-foo", stub_modules=["typed_dep5"]),
            # A 3rd-party dependency can have both a type stub and implementation.
            req("req2", "req2==1"),
            req("req2_types", "types-req2==1"),
            req("req3", "req3==1"),
            req("req3_types", "req3-types==1"),
            req("req4", "req4==1"),
            req("req4_types", "req4-stubs==1", stub_modules=["req4"]),
            # Ambiguous.
            req("ambiguous_t1", "ambiguous==1.2"),
            req("ambiguous_t2", "ambiguous==1.3"),
            req("ambiguous_stubs_t1", "ambiguous-stubs-types==1.3"),
            req("ambiguous_stubs_t2", "types-ambiguous-stubs==1.3"),
            # If there's ambiguity within type stubs or within implementations, then there should
            # be ambiguity with the other category too.
            req("ambiguous_again_t1", "ambiguous-again==1.2"),
            req("ambiguous_again_t2", "ambiguous-again==1.3"),
            req("ambiguous_again_t3", "ambiguous-again-types==1.3"),
            req("ambiguous_again_stubby_t1", "ambiguous-again-stubby-types==1.2"),
            req("ambiguous_again_stubby_t2", "types-ambiguous-again-stubby==1.3"),
            req("ambiguous_again_stubby_t3", "ambiguous-again-stubby==1.3"),
            # Only assume it's a type stubs dep if we are certain it's not an implementation.
            req("looks_like_stubs", "looks-like-stubs-types", modules=["looks_like_stubs"]),
        ]
    )
    rule_runner.write_files({"BUILD": build_file})
    result = rule_runner.request(ThirdPartyPythonModuleMapping, [])
    assert result == ThirdPartyPythonModuleMapping(
        mapping=FrozenDict(
            {
                "file_dist": (Address("", target_name="file_dist"),),
                "looks_like_stubs": (Address("", target_name="looks_like_stubs"),),
                "mapped_module": (Address("", target_name="modules"),),
                "module_mapping_un_normalized": (
                    Address("", target_name="module_mapping_un_normalized"),
                ),
                "req1": (Address("", target_name="req1"),),
                "req2": (Address("", target_name="req2"), Address("", target_name="req2_types")),
                "req3": (Address("", target_name="req3"), Address("", target_name="req3_types")),
                "req4": (Address("", target_name="req4"), Address("", target_name="req4_types")),
                "typed_dep1": (Address("", target_name="typed-dep1"),),
                "typed_dep2": (Address("", target_name="typed-dep2"),),
                "typed_dep3": (Address("", target_name="typed-dep3"),),
                "typed_dep4": (Address("", target_name="typed-dep4"),),
                "typed_dep5": (Address("", target_name="typed-dep5"),),
                "un_normalized_project": (Address("", target_name="un_normalized"),),
                "vcs_dist": (Address("", target_name="vcs_dist"),),
            }
        ),
        ambiguous_modules=FrozenDict(
            {
                "ambiguous": (
                    Address("", target_name="ambiguous_t1"),
                    Address("", target_name="ambiguous_t2"),
                ),
                "ambiguous_again": (
                    Address("", target_name="ambiguous_again_t1"),
                    Address("", target_name="ambiguous_again_t2"),
                    Address("", target_name="ambiguous_again_t3"),
                ),
                "ambiguous_again_stubby": (
                    Address("", target_name="ambiguous_again_stubby_t1"),
                    Address("", target_name="ambiguous_again_stubby_t2"),
                    Address("", target_name="ambiguous_again_stubby_t3"),
                ),
                "ambiguous_stubs": (
                    Address("", target_name="ambiguous_stubs_t1"),
                    Address("", target_name="ambiguous_stubs_t2"),
                ),
            }
        ),
    )


def test_map_module_to_address(rule_runner: RuleRunner) -> None:
    def assert_owners(
        module: str, expected: list[Address], expected_ambiguous: list[Address] | None = None
    ) -> None:
        owners = rule_runner.request(PythonModuleOwners, [PythonModule(module)])
        assert list(owners.unambiguous) == expected
        assert list(owners.ambiguous) == (expected_ambiguous or [])

        from_import_owners = rule_runner.request(
            PythonModuleOwners, [PythonModule(f"{module}.Class")]
        )
        assert list(from_import_owners.unambiguous) == expected
        assert list(from_import_owners.ambiguous) == (expected_ambiguous or [])

    rule_runner.set_options(["--source-root-patterns=['root', '/']"])
    rule_runner.write_files(
        {
            # A root-level module.
            "script.py": "",
            "BUILD": dedent(
                """\
                python_source(name="script", source="script.py")
                python_requirement(name="valid_dep", requirements=["valid_dep"])
                # Dependency with a type stub.
                python_requirement(name="dep_w_stub", requirements=["dep_w_stub"])
                python_requirement(name="dep_w_stub-types", requirements=["dep_w_stub-types"])
                """
            ),
            # Normal first-party module.
            "root/no_stub/app.py": "",
            "root/no_stub/BUILD": "python_sources()",
            # First-party module with type stub.
            "root/stub/app.py": "",
            "root/stub/app.pyi": "",
            "root/stub/BUILD": "python_sources()",
            # Package path.
            "root/package/subdir/__init__.py": "",
            "root/package/subdir/BUILD": "python_sources()",
            # Third-party requirement with first-party type stub.
            "root/dep_with_stub.pyi": "",
            "root/BUILD": dedent(
                """\
                python_sources()
                python_requirement(name="dep", requirements=["dep_with_stub"])
                """
            ),
            # Ambiguity.
            "root/ambiguous/f1.py": "",
            "root/ambiguous/f2.py": "",
            "root/ambiguous/f3.py": "",
            "root/ambiguous/f4.pyi": "",
            "root/ambiguous/BUILD": dedent(
                """\
                # Ambiguity purely within third-party deps.
                python_requirement(name='thirdparty1', requirements=['ambiguous_3rdparty'])
                python_requirement(name='thirdparty2', requirements=['ambiguous_3rdparty'])

                # Ambiguity purely within first-party deps.
                python_source(name="firstparty1", source="f1.py")
                python_source(name="firstparty2", source="f1.py")

                # Ambiguity within third-party, which should result in ambiguity for first-party
                # too. These all share the module `ambiguous.f2`.
                python_requirement(
                    name='thirdparty3', requirements=['bar'], module_mapping={'bar': ['ambiguous.f2']}
                )
                python_requirement(
                    name='thirdparty4', requirements=['bar'], module_mapping={'bar': ['ambiguous.f2']}
                )
                python_source(name="firstparty3", source="f2.py")

                # Ambiguity within first-party, which should result in ambiguity for third-party
                # too. These all share the module `ambiguous.f3`.
                python_source(name="firstparty4", source="f3.py")
                python_source(name="firstparty5", source="f3.py")
                python_requirement(
                    name='thirdparty5', requirements=['baz'], module_mapping={'baz': ['ambiguous.f3']}
                )

                # You can only write a first-party type stub for a third-party requirement if
                # there are not third-party type stubs already.
                python_requirement(
                    name='ambiguous-stub',
                    requirements=['ambiguous-stub'],
                    module_mapping={"ambiguous-stub": ["ambiguous.f4"]},
                )
                python_requirement(
                    name='ambiguous-stub-types',
                    requirements=['ambiguous-stub-types'],
                    type_stubs_module_mapping={"ambiguous-stub-types": ["ambiguous.f4"]},
                )
                python_source(name='ambiguous-stub-1stparty', source='f4.pyi')
                """
            ),
        }
    )

    assert_owners("pathlib", [])
    assert_owners("typing", [])
    assert_owners("valid_dep", [Address("", target_name="valid_dep")])
    assert_owners(
        "dep_w_stub",
        [Address("", target_name="dep_w_stub"), Address("", target_name="dep_w_stub-types")],
    )
    assert_owners("script", [Address("", target_name="script")])
    assert_owners("no_stub.app", expected=[Address("root/no_stub", relative_file_path="app.py")])
    assert_owners(
        "stub.app",
        [
            Address("root/stub", relative_file_path="app.py"),
            Address("root/stub", relative_file_path="app.pyi"),
        ],
    )
    assert_owners(
        "package.subdir", [Address("root/package/subdir", relative_file_path="__init__.py")]
    )
    assert_owners(
        "dep_with_stub",
        [
            Address("root", target_name="dep"),
            Address("root", relative_file_path="dep_with_stub.pyi"),
        ],
    )

    assert_owners(
        "ambiguous_3rdparty",
        [],
        expected_ambiguous=[
            Address("root/ambiguous", target_name="thirdparty1"),
            Address("root/ambiguous", target_name="thirdparty2"),
        ],
    )
    assert_owners(
        "ambiguous.f1",
        [],
        expected_ambiguous=[
            Address("root/ambiguous", target_name="firstparty1"),
            Address("root/ambiguous", target_name="firstparty2"),
        ],
    )
    assert_owners(
        "ambiguous.f2",
        [],
        expected_ambiguous=[
            Address("root/ambiguous", target_name="firstparty3"),
            Address("root/ambiguous", target_name="thirdparty3"),
            Address("root/ambiguous", target_name="thirdparty4"),
        ],
    )
    assert_owners(
        "ambiguous.f3",
        [],
        expected_ambiguous=[
            Address("root/ambiguous", target_name="firstparty4"),
            Address("root/ambiguous", target_name="firstparty5"),
            Address("root/ambiguous", target_name="thirdparty5"),
        ],
    )
    assert_owners(
        "ambiguous.f4",
        [],
        expected_ambiguous=[
            Address("root/ambiguous", target_name="ambiguous-stub"),
            Address("root/ambiguous", target_name="ambiguous-stub-1stparty"),
            Address("root/ambiguous", target_name="ambiguous-stub-types"),
        ],
    )
