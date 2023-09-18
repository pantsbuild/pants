# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import re
from pathlib import PurePath
from textwrap import dedent
from types import FunctionType
from typing import Iterable

import pytest
from packaging.utils import canonicalize_name as canonicalize_project_name

from pants.backend.codegen.protobuf.python import python_protobuf_module_mapper
from pants.backend.codegen.protobuf.python.additional_fields import (
    rules as protobuf_additional_fields_rules,
)
from pants.backend.codegen.protobuf.target_types import ProtobufSourcesGeneratorTarget
from pants.backend.codegen.protobuf.target_types import rules as protobuf_target_type_rules
from pants.backend.python import target_types_rules
from pants.backend.python.dependency_inference.default_module_mapping import (
    DEFAULT_MODULE_MAPPING,
    DEFAULT_MODULE_PATTERN_MAPPING,
    DEFAULT_TYPE_STUB_MODULE_MAPPING,
    first_group_hyphen_to_underscore,
    two_groups_hyphens_two_replacements_with_suffix,
)
from pants.backend.python.dependency_inference.module_mapper import (
    FirstPartyPythonModuleMapping,
    ModuleProvider,
    ModuleProviderType,
    PossibleModuleProvider,
    PythonModuleOwners,
    PythonModuleOwnersRequest,
    ThirdPartyPythonModuleMapping,
    generate_mappings_from_pattern,
    module_from_stripped_path,
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


def test_default_module_mapping_is_normalized() -> None:
    for k in DEFAULT_MODULE_MAPPING:
        assert k == canonicalize_project_name(
            k
        ), "Please update `DEFAULT_MODULE_MAPPING` to use canonical project names"
    for k in DEFAULT_TYPE_STUB_MODULE_MAPPING:
        assert k == canonicalize_project_name(
            k
        ), "Please update `DEFAULT_TYPE_STUB_MODULE_MAPPING` to use canonical project names"


def test_default_module_mapping_uses_tuples() -> None:
    for modules in DEFAULT_MODULE_MAPPING.values():
        assert isinstance(modules, tuple)
        assert len(modules) > 0


def test_default_module_pattern_mapping_keys_and_value_types() -> None:
    for pattern, replacements in DEFAULT_MODULE_PATTERN_MAPPING.items():
        assert isinstance(pattern, re.Pattern)
        assert isinstance(replacements, Iterable)
        for replacement in replacements:
            assert (
                isinstance(replacement, FunctionType)
                or isinstance(replacement, str)
                or callable(replacement)
            )


@pytest.mark.parametrize(
    "stripped_path,expected",
    [
        ("top_level.py", "top_level"),
        ("top_level.pyi", "top_level"),
        ("dir/subdir/__init__.py", "dir.subdir"),
        ("dir/subdir/__init__.pyi", "dir.subdir"),
        ("dir/subdir/app.py", "dir.subdir.app"),
        ("src/python/project/not_stripped.py", "src.python.project.not_stripped"),
    ],
)
def test_module_from_stripped_path(stripped_path: str, expected: str) -> None:
    assert module_from_stripped_path(PurePath(stripped_path)) == expected


def test_first_party_modules_mapping() -> None:
    root_provider = ModuleProvider(
        Address("", relative_file_path="root.py"), ModuleProviderType.IMPL
    )
    util_provider = ModuleProvider(
        Address("src/python/util", relative_file_path="strutil.py"), ModuleProviderType.IMPL
    )
    util_stubs_provider = ModuleProvider(
        Address("src/python/util", relative_file_path="strutil.pyi"), ModuleProviderType.TYPE_STUB
    )
    test_provider = ModuleProvider(
        Address("tests/python/project_test", relative_file_path="test.py"), ModuleProviderType.IMPL
    )
    mapping = FirstPartyPythonModuleMapping(
        FrozenDict(
            {
                "default": FrozenDict(
                    {
                        "root": (root_provider,),
                        "util.strutil": (util_provider, util_stubs_provider),
                        "project_test.test": (test_provider,),
                        "ambiguous": (root_provider, util_provider),
                        "util.ambiguous": (util_provider, test_provider),
                        "two_resolves": (root_provider,),
                    }
                ),
                "another": FrozenDict({"two_resolves": (test_provider,)}),
            }
        )
    )

    def assert_addresses(
        mod: str, expected: tuple[PossibleModuleProvider, ...], *, resolve: str | None = None
    ) -> None:
        assert mapping.providers_for_module(mod, resolve=resolve) == expected

    root_provider0 = PossibleModuleProvider(root_provider, 0)
    root_provider1 = PossibleModuleProvider(root_provider, 1)
    util_provider0 = PossibleModuleProvider(util_provider, 0)
    util_provider1 = PossibleModuleProvider(util_provider, 1)
    util_stubs_provider0 = PossibleModuleProvider(util_stubs_provider, 0)
    util_stubs_provider1 = PossibleModuleProvider(util_stubs_provider, 1)
    test_provider0 = PossibleModuleProvider(test_provider, 0)
    test_provider1 = PossibleModuleProvider(test_provider, 1)

    assert_addresses("root", (root_provider0,))
    assert_addresses("root.func", (root_provider1,))
    assert_addresses("root.submodule.func", ())

    assert_addresses("util.strutil", (util_provider0, util_stubs_provider0))
    assert_addresses("util.strutil.ensure_text", (util_provider1, util_stubs_provider1))
    assert_addresses("util", ())

    assert_addresses("project_test.test", (test_provider0,))
    assert_addresses("project_test.test.TestDemo", (test_provider1,))
    assert_addresses("project_test", ())
    assert_addresses("project.test", ())

    assert_addresses("ambiguous", (root_provider0, util_provider0))
    assert_addresses("ambiguous.func", (root_provider1, util_provider1))
    assert_addresses("ambiguous.submodule.func", ())

    assert_addresses("util.ambiguous", (util_provider0, test_provider0))
    assert_addresses("util.ambiguous.Foo", (util_provider1, test_provider1))
    assert_addresses("util.ambiguous.Foo.method", ())

    assert_addresses("two_resolves", (root_provider0, test_provider0), resolve=None)
    assert_addresses("two_resolves.foo", (root_provider1, test_provider1), resolve=None)
    assert_addresses("two_resolves.foo.bar", (), resolve=None)
    assert_addresses("two_resolves", (root_provider0,), resolve="default")
    assert_addresses("two_resolves", (test_provider0,), resolve="another")


def test_third_party_modules_mapping() -> None:
    colors_provider = ModuleProvider(Address("", target_name="ansicolors"), ModuleProviderType.IMPL)
    colors_stubs_provider = ModuleProvider(
        Address("", target_name="types-ansicolors"), ModuleProviderType.TYPE_STUB
    )
    pants_provider = ModuleProvider(Address("", target_name="pantsbuild"), ModuleProviderType.IMPL)
    pants_testutil_provider = ModuleProvider(
        Address("", target_name="pantsbuild.testutil"), ModuleProviderType.IMPL
    )
    submodule_provider = ModuleProvider(
        Address("", target_name="submodule"), ModuleProviderType.IMPL
    )
    mapping = ThirdPartyPythonModuleMapping(
        FrozenDict(
            {
                "default-resolve": FrozenDict(
                    {
                        "colors": (colors_provider, colors_stubs_provider),
                        "pants": (pants_provider,),
                        "req.submodule": (submodule_provider,),
                        "pants.testutil": (pants_testutil_provider,),
                        "two_resolves": (colors_provider,),
                    }
                ),
                "another-resolve": FrozenDict({"two_resolves": (pants_provider,)}),
            }
        )
    )

    def assert_addresses(
        mod: str, expected: tuple[PossibleModuleProvider, ...], *, resolve: str | None = None
    ) -> None:
        assert mapping.providers_for_module(mod, resolve) == expected

    colors_provider0 = PossibleModuleProvider(colors_provider, 0)
    colors_provider1 = PossibleModuleProvider(colors_provider, 1)
    colors_provider2 = PossibleModuleProvider(colors_provider, 2)
    colors_stubs_provider0 = PossibleModuleProvider(colors_stubs_provider, 0)
    colors_stubs_provider1 = PossibleModuleProvider(colors_stubs_provider, 1)
    pants_provider0 = PossibleModuleProvider(pants_provider, 0)
    pants_provider1 = PossibleModuleProvider(pants_provider, 1)
    pants_provider2 = PossibleModuleProvider(pants_provider, 2)
    pants_provider3 = PossibleModuleProvider(pants_provider, 3)
    pants_testutil_provider0 = PossibleModuleProvider(pants_testutil_provider, 0)
    pants_testutil_provider1 = PossibleModuleProvider(pants_testutil_provider, 1)
    submodule_provider0 = PossibleModuleProvider(submodule_provider, 0)
    submodule_provider1 = PossibleModuleProvider(submodule_provider, 1)

    assert_addresses("colors", (colors_provider0, colors_stubs_provider0))
    assert_addresses("colors.red", (colors_provider1, colors_stubs_provider1))

    assert_addresses("pants", (pants_provider0,))
    assert_addresses("pants.task", (pants_provider1,))
    assert_addresses("pants.task.task", (pants_provider2,))
    assert_addresses("pants.task.task.Task", (pants_provider3,))

    assert_addresses("pants.testutil", (pants_testutil_provider0,))
    assert_addresses("pants.testutil.foo", (pants_testutil_provider1,))

    assert_addresses("req.submodule", (submodule_provider0,))
    assert_addresses("req.submodule.foo", (submodule_provider1,))
    assert_addresses("req.another", ())
    assert_addresses("req", ())

    assert_addresses("unknown", ())
    assert_addresses("unknown.pants", ())

    assert_addresses("two_resolves", (colors_provider0, pants_provider0), resolve=None)
    assert_addresses("two_resolves.foo", (colors_provider1, pants_provider1), resolve=None)
    assert_addresses("two_resolves.foo.bar", (colors_provider2, pants_provider2), resolve=None)
    assert_addresses("two_resolves", (colors_provider0,), resolve="default-resolve")
    assert_addresses("two_resolves", (pants_provider0,), resolve="another-resolve")


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *stripped_source_files.rules(),
            *module_mapper_rules(),
            *python_protobuf_module_mapper.rules(),
            *target_types_rules.rules(),
            *protobuf_additional_fields_rules(),
            *protobuf_target_type_rules(),
            QueryRule(FirstPartyPythonModuleMapping, []),
            QueryRule(ThirdPartyPythonModuleMapping, []),
            QueryRule(PythonModuleOwners, [PythonModuleOwnersRequest]),
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
        [
            "--source-root-patterns=['src/python', 'tests/python', 'build-support']",
            "--python-enable-resolves",
            "--python-resolves={'python-default': '', 'another-resolve': ''}",
        ]
    )
    rule_runner.write_files(
        {
            "src/python/project/util/dirutil.py": "",
            "src/python/project/util/tarutil.py": "",
            "src/python/project/util/BUILD": "python_sources(resolve='another-resolve')",
            # A module with multiple owners, including type stubs.
            "src/python/multiple_owners.py": "",
            "src/python/multiple_owners.pyi": "",
            "src/python/BUILD": "python_sources()",
            "build-support/multiple_owners.py": "",
            "build-support/BUILD": "python_sources()",
            # A package module.
            "tests/python/project_test/demo_test/__init__.py": "",
            "tests/python/project_test/demo_test/BUILD": "python_sources()",
            # Check that plugin mappings work. Note that we duplicate one of the files with a normal
            # python_source.
            "src/python/protos/f1.proto": "",
            "src/python/protos/f2.proto": "",
            "src/python/protos/f2_pb2.py": "",
            "src/python/protos/BUILD": dedent(
                """\
                protobuf_sources(name='protos')
                python_source(name='py', source="f2_pb2.py")
                """
            ),
        }
    )

    result = rule_runner.request(FirstPartyPythonModuleMapping, [])
    assert result == FirstPartyPythonModuleMapping(
        FrozenDict(
            {
                "another-resolve": FrozenDict(
                    {
                        "project.util.dirutil": (
                            ModuleProvider(
                                Address("src/python/project/util", relative_file_path="dirutil.py"),
                                ModuleProviderType.IMPL,
                            ),
                        ),
                        "project.util.tarutil": (
                            ModuleProvider(
                                Address("src/python/project/util", relative_file_path="tarutil.py"),
                                ModuleProviderType.IMPL,
                            ),
                        ),
                    }
                ),
                "python-default": FrozenDict(
                    {
                        "multiple_owners": (
                            ModuleProvider(
                                Address("build-support", relative_file_path="multiple_owners.py"),
                                ModuleProviderType.IMPL,
                            ),
                            ModuleProvider(
                                Address("src/python", relative_file_path="multiple_owners.py"),
                                ModuleProviderType.IMPL,
                            ),
                            ModuleProvider(
                                Address("src/python", relative_file_path="multiple_owners.pyi"),
                                ModuleProviderType.TYPE_STUB,
                            ),
                        ),
                        "project_test.demo_test": (
                            ModuleProvider(
                                Address(
                                    "tests/python/project_test/demo_test",
                                    relative_file_path="__init__.py",
                                ),
                                ModuleProviderType.IMPL,
                            ),
                        ),
                        "protos.f1_pb2": (
                            ModuleProvider(
                                Address(
                                    "src/python/protos",
                                    relative_file_path="f1.proto",
                                    target_name="protos",
                                ),
                                ModuleProviderType.IMPL,
                            ),
                        ),
                        "protos.f2_pb2": (
                            ModuleProvider(
                                Address("src/python/protos", target_name="py"),
                                ModuleProviderType.IMPL,
                            ),
                            ModuleProvider(
                                Address(
                                    "src/python/protos",
                                    relative_file_path="f2.proto",
                                    target_name="protos",
                                ),
                                ModuleProviderType.IMPL,
                            ),
                        ),
                    }
                ),
            }
        )
    )


def test_map_third_party_modules_to_addresses(rule_runner: RuleRunner) -> None:
    def req(
        tgt_name: str,
        req_str: str,
        *,
        modules: list[str] | None = None,
        stub_modules: list[str] | None = None,
        resolve: str = "default",
    ) -> str:
        return dedent(
            f"""\
            python_requirement(name='{tgt_name}', requirements=['{req_str}'],
            modules={modules or []},
            type_stub_modules={stub_modules or []},
            resolve={repr(resolve)})
            """
        )

    build_file = "\n\n".join(
        [
            req("req1", "req1==1.2"),
            req("un_normalized", "Un-Normalized-Project>3"),
            req("file_dist", "file_dist@ file:///path/to/dist.whl"),
            req("vcs_dist", "vcs_dist@ git+https://github.com/vcs/dist.git"),
            req("modules", "foo==1", modules=["mapped_module"]),
            # We extract the module from type stub dependencies.
            req("typed-dep1", "typed-dep1-types"),
            req("typed-dep2", "types-typed-dep2"),
            req("typed-dep3", "typed-dep3-stubs"),
            req("typed-dep4", "stubs-typed-dep4"),
            req("typed-dep5", "typed-dep5-foo", stub_modules=["typed_dep5"]),
            # A 3rd-party dependency can have both a type stub and implementation.
            req("multiple_owners1", "multiple_owners==1"),
            req("multiple_owners2", "multiple_owners==2", resolve="another"),
            req("multiple_owners_types", "types-multiple_owners==1", resolve="another"),
            # Only assume it's a type stubs dep if we are certain it's not an implementation.
            req("looks_like_stubs", "looks-like-stubs-types", modules=["looks_like_stubs"]),
            req("google-cloud-hardyhar", "google-cloud-hardyhar"),
            req("google-cloud-secret-manager", "google-cloud-secret-manager"),
            req("azure-keyvault-secrets", "azure-keyvault-secrets"),
            req("django-model-utils", "model_utils"),
            req("django-taggit", "taggit"),
            req("opentelemetry-instrumentation-botocore", "opentelemetry-instrumentation-botocore"),
        ]
    )
    rule_runner.write_files({"BUILD": build_file})
    rule_runner.set_options(
        ["--python-resolves={'default': '', 'another': ''}", "--python-enable-resolves"]
    )
    result = rule_runner.request(ThirdPartyPythonModuleMapping, [])
    expected = ThirdPartyPythonModuleMapping(
        FrozenDict(
            {
                "another": FrozenDict(
                    {
                        "multiple_owners": (
                            ModuleProvider(
                                Address("", target_name="multiple_owners2"), ModuleProviderType.IMPL
                            ),
                            ModuleProvider(
                                Address("", target_name="multiple_owners_types"),
                                ModuleProviderType.TYPE_STUB,
                            ),
                        ),
                    }
                ),
                "default": FrozenDict(
                    {
                        "azure.keyvault.secrets": (
                            ModuleProvider(
                                Address("", target_name="azure-keyvault-secrets"),
                                ModuleProviderType.IMPL,
                            ),
                        ),
                        "azure_keyvault_secrets": (
                            ModuleProvider(
                                Address("", target_name="azure-keyvault-secrets"),
                                ModuleProviderType.IMPL,
                            ),
                        ),
                        "file_dist": (
                            ModuleProvider(
                                Address("", target_name="file_dist"), ModuleProviderType.IMPL
                            ),
                        ),
                        "google.cloud.hardyhar": (
                            ModuleProvider(
                                Address("", target_name="google-cloud-hardyhar"),
                                ModuleProviderType.IMPL,
                            ),
                        ),
                        "google.cloud.hardyhar_v1": (
                            ModuleProvider(
                                Address("", target_name="google-cloud-hardyhar"),
                                ModuleProviderType.IMPL,
                            ),
                        ),
                        "google.cloud.hardyhar_v2": (
                            ModuleProvider(
                                Address("", target_name="google-cloud-hardyhar"),
                                ModuleProviderType.IMPL,
                            ),
                        ),
                        "google.cloud.hardyhar_v3": (
                            ModuleProvider(
                                Address("", target_name="google-cloud-hardyhar"),
                                ModuleProviderType.IMPL,
                            ),
                        ),
                        "google.cloud.secretmanager": (
                            ModuleProvider(
                                Address("", target_name="google-cloud-secret-manager"),
                                ModuleProviderType.IMPL,
                            ),
                        ),
                        "google.cloud.secretmanager_v1": (
                            ModuleProvider(
                                Address("", target_name="google-cloud-secret-manager"),
                                ModuleProviderType.IMPL,
                            ),
                        ),
                        "google.cloud.secretmanager_v2": (
                            ModuleProvider(
                                Address("", target_name="google-cloud-secret-manager"),
                                ModuleProviderType.IMPL,
                            ),
                        ),
                        "google.cloud.secretmanager_v3": (
                            ModuleProvider(
                                Address("", target_name="google-cloud-secret-manager"),
                                ModuleProviderType.IMPL,
                            ),
                        ),
                        # this is the fallback
                        "google_cloud_hardyhar": (
                            ModuleProvider(
                                Address("", target_name="google-cloud-hardyhar"),
                                ModuleProviderType.IMPL,
                            ),
                        ),
                        # this is the fallback
                        "google_cloud_secret_manager": (
                            ModuleProvider(
                                Address("", target_name="google-cloud-secret-manager"),
                                ModuleProviderType.IMPL,
                            ),
                        ),
                        "looks_like_stubs": (
                            ModuleProvider(
                                Address("", target_name="looks_like_stubs"), ModuleProviderType.IMPL
                            ),
                        ),
                        "mapped_module": (
                            ModuleProvider(
                                Address("", target_name="modules"), ModuleProviderType.IMPL
                            ),
                        ),
                        "model_utils": (
                            ModuleProvider(
                                Address("", target_name="django-model-utils"),
                                ModuleProviderType.IMPL,
                            ),
                        ),
                        "multiple_owners": (
                            ModuleProvider(
                                Address("", target_name="multiple_owners1"), ModuleProviderType.IMPL
                            ),
                        ),
                        "opentelemetry.instrumentation.botocore": (
                            ModuleProvider(
                                Address("", target_name="opentelemetry-instrumentation-botocore"),
                                ModuleProviderType.IMPL,
                            ),
                        ),
                        "opentelemetry_instrumentation_botocore": (
                            ModuleProvider(
                                Address("", target_name="opentelemetry-instrumentation-botocore"),
                                ModuleProviderType.IMPL,
                            ),
                        ),
                        "req1": (
                            ModuleProvider(
                                Address("", target_name="req1"), ModuleProviderType.IMPL
                            ),
                        ),
                        "taggit": (
                            ModuleProvider(
                                Address("", target_name="django-taggit"),
                                ModuleProviderType.IMPL,
                            ),
                        ),
                        "typed_dep1": (
                            ModuleProvider(
                                Address("", target_name="typed-dep1"), ModuleProviderType.TYPE_STUB
                            ),
                        ),
                        "typed_dep2": (
                            ModuleProvider(
                                Address("", target_name="typed-dep2"), ModuleProviderType.TYPE_STUB
                            ),
                        ),
                        "typed_dep3": (
                            ModuleProvider(
                                Address("", target_name="typed-dep3"), ModuleProviderType.TYPE_STUB
                            ),
                        ),
                        "typed_dep4": (
                            ModuleProvider(
                                Address("", target_name="typed-dep4"), ModuleProviderType.TYPE_STUB
                            ),
                        ),
                        "typed_dep5": (
                            ModuleProvider(
                                Address("", target_name="typed-dep5"), ModuleProviderType.TYPE_STUB
                            ),
                        ),
                        "un_normalized_project": (
                            ModuleProvider(
                                Address("", target_name="un_normalized"), ModuleProviderType.IMPL
                            ),
                        ),
                        "vcs_dist": (
                            ModuleProvider(
                                Address("", target_name="vcs_dist"), ModuleProviderType.IMPL
                            ),
                        ),
                    }
                ),
            }
        )
    )
    print(result)
    print(expected)
    assert result == expected


def test_map_module_to_address(rule_runner: RuleRunner) -> None:
    def assert_owners(
        module: str, expected: list[Address], expected_ambiguous: list[Address] | None = None
    ) -> None:
        owners = rule_runner.request(
            PythonModuleOwners, [PythonModuleOwnersRequest(module, resolve="python-default")]
        )
        assert list(owners.unambiguous) == expected
        assert list(owners.ambiguous) == (expected_ambiguous or [])

        from_import_owners = rule_runner.request(
            PythonModuleOwners,
            [PythonModuleOwnersRequest(f"{module}.Class", resolve="python-default")],
        )
        assert list(from_import_owners.unambiguous) == expected
        assert list(from_import_owners.ambiguous) == (expected_ambiguous or [])

    rule_runner.set_options(["--source-root-patterns=['root', '/']", "--python-enable-resolves"])
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
            # Namespace package split between first- and third-party, disambiguated by ancestry level.
            "root/namespace/__init__.py": "",
            "root/namespace/BUILD": dedent(
                """\
                python_requirement(name="thirdparty", requirements=["namespace.thirdparty"])
                python_source(name="init", source="__init__.py")
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
                    name='thirdparty3', requirements=['bar'], modules=['ambiguous.f2']
                )
                python_requirement(
                    name='thirdparty4', requirements=['bar'], modules=['ambiguous.f2']
                )
                python_source(name="firstparty3", source="f2.py")

                # Ambiguity within first-party, which should result in ambiguity for third-party
                # too. These all share the module `ambiguous.f3`.
                python_source(name="firstparty4", source="f3.py")
                python_source(name="firstparty5", source="f3.py")
                python_requirement(
                    name='thirdparty5', requirements=['baz'], modules=['ambiguous.f3']
                )

                # You can only write a first-party type stub for a third-party requirement if
                # there are not third-party type stubs already.
                python_requirement(
                    name='ambiguous-stub',
                    requirements=['ambiguous-stub'],
                    modules=["ambiguous.f4"],
                )
                python_requirement(
                    name='ambiguous-stub-types',
                    requirements=['ambiguous-stub-types'],
                    type_stub_modules=["ambiguous.f4"],
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
    assert_owners("namespace.thirdparty", [Address("root/namespace", target_name="thirdparty")])

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
            Address("root/ambiguous", target_name="thirdparty3"),
            Address("root/ambiguous", target_name="thirdparty4"),
            Address("root/ambiguous", target_name="firstparty3"),
        ],
    )
    assert_owners(
        "ambiguous.f3",
        [],
        expected_ambiguous=[
            Address("root/ambiguous", target_name="thirdparty5"),
            Address("root/ambiguous", target_name="firstparty4"),
            Address("root/ambiguous", target_name="firstparty5"),
        ],
    )
    assert_owners(
        "ambiguous.f4",
        [],
        expected_ambiguous=[
            Address("root/ambiguous", target_name="ambiguous-stub"),
            Address("root/ambiguous", target_name="ambiguous-stub-types"),
            Address("root/ambiguous", target_name="ambiguous-stub-1stparty"),
        ],
    )


def test_resolving_ambiguity_by_filesystem_proximity(rule_runner: RuleRunner) -> None:
    rule_runner.set_options(
        [
            "--source-root-patterns=['root1', 'root2', 'root3']",
            "--python-infer-ambiguity-resolution=by_source_root",
        ]
    )
    rule_runner.write_files(
        {
            "root1/aa/bb/BUILD": "python_sources()",
            "root1/aa/bb/foo.py": "",
            "root1/aa/cc/BUILD": "python_sources()",
            "root1/aa/cc/bar.py": "from aa.bb import foo",
            "root2/aa/bb/BUILD": "python_sources()",
            "root2/aa/bb/foo.py": "",
            "root2/aa/dd/baz.py": "from aa.bb import foo",
            "root3/aa/ee/BUILD": "python_sources()",
            "root3/aa/ee/foo.py": "from aa.bb import foo",
        }
    )

    owners = rule_runner.request(
        PythonModuleOwners, [PythonModuleOwnersRequest("aa.bb.foo", None, locality=None)]
    )
    assert list(owners.unambiguous) == []
    assert list(owners.ambiguous) == [
        Address("root1/aa/bb", relative_file_path="foo.py"),
        Address("root2/aa/bb", relative_file_path="foo.py"),
    ]

    owners = rule_runner.request(
        PythonModuleOwners, [PythonModuleOwnersRequest("aa.bb.foo", None, locality="root1/")]
    )
    assert list(owners.unambiguous) == [Address("root1/aa/bb", relative_file_path="foo.py")]
    assert list(owners.ambiguous) == []

    owners = rule_runner.request(
        PythonModuleOwners, [PythonModuleOwnersRequest("aa.bb.foo", None, locality="root2/")]
    )
    assert list(owners.unambiguous) == [Address("root2/aa/bb", relative_file_path="foo.py")]
    assert list(owners.ambiguous) == []

    owners = rule_runner.request(
        PythonModuleOwners, [PythonModuleOwnersRequest("aa.bb.foo", None, locality="root3/")]
    )
    assert list(owners.unambiguous) == []
    assert list(owners.ambiguous) == [
        Address("root1/aa/bb", relative_file_path="foo.py"),
        Address("root2/aa/bb", relative_file_path="foo.py"),
    ]


def test_map_module_considers_resolves(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "BUILD": dedent(
                """\
                # Note that both `python_requirements` have the same `dep`, which would normally
                # result in ambiguity.
                python_requirement(
                    name="dep1",
                    resolve="a",
                    requirements=["dep"],
                )

                python_requirement(
                    name="dep2",
                    resolve="b",
                    requirements=["dep"],
                )
                """
            )
        }
    )
    rule_runner.set_options(["--python-resolves={'a': '', 'b': ''}", "--python-enable-resolves"])

    def get_owners(resolve: str | None) -> PythonModuleOwners:
        return rule_runner.request(PythonModuleOwners, [PythonModuleOwnersRequest("dep", resolve)])

    assert get_owners("a").unambiguous == (Address("", target_name="dep1"),)
    assert get_owners("b").unambiguous == (Address("", target_name="dep2"),)
    assert get_owners(None).ambiguous == (
        Address("", target_name="dep1"),
        Address("", target_name="dep2"),
    )


def test_issue_15111(rule_runner: RuleRunner) -> None:
    """Ensure we can handle when a single address provides multiple modules.

    This is currently only possible with third-party targets.
    """
    rule_runner.write_files(
        {"BUILD": "python_requirement(name='req', requirements=['docopt', 'types-docopt'])"}
    )
    rule_runner.set_options(["--python-enable-resolves"])
    result = rule_runner.request(ThirdPartyPythonModuleMapping, [])
    assert result == ThirdPartyPythonModuleMapping(
        FrozenDict(
            {
                "python-default": FrozenDict(
                    {
                        "docopt": (
                            ModuleProvider(Address("", target_name="req"), ModuleProviderType.IMPL),
                            ModuleProvider(
                                Address("", target_name="req"), ModuleProviderType.TYPE_STUB
                            ),
                        ),
                    }
                )
            }
        )
    )


@pytest.mark.parametrize(
    ("proj_name", "expected_modules"),
    [
        (
            "google-cloud-hardyhar",
            [
                "google.cloud.hardyhar",
                "google.cloud.hardyhar_v1",
                "google.cloud.hardyhar_v2",
                "google.cloud.hardyhar_v3",
            ],
        ),
        (
            "python-jose",
            ["jose"],
        ),
        ("opentelemetry-instrumentation-tornado", ["opentelemetry.instrumentation.tornado"]),
        ("azure-mgmt-consumption", ["azure.mgmt.consumption"]),
        ("azure-keyvault", ["azure.keyvault"]),
        (
            "django-admin-cursor-paginator",
            [
                "admin_cursor_paginator",
            ],
        ),
        (
            "django-dotenv",
            [
                "dotenv",
            ],
        ),
        ("oslo-service", ["oslo_service"]),
        ("pyopenssl", []),
        ("", []),
    ],
)
def test_generate_mappings_from_pattern_matches_para(
    proj_name: str, expected_modules: list[str]
) -> None:
    assert generate_mappings_from_pattern(proj_name) == expected_modules


def test_number_of_capture_groups_for_functions() -> None:
    with pytest.raises(ValueError):
        re.sub("foo", first_group_hyphen_to_underscore, "foo")
    with pytest.raises(ValueError):
        re.sub("foo", two_groups_hyphens_two_replacements_with_suffix, "foo")
