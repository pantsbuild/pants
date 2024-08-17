# Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from pants.core.util_rules.config_files import rules as config_files_rules
from typing import Iterable

import pytest

from pants.backend.openapi.codegen.python.generate import GeneratePythonFromOpenAPIRequest
from pants.backend.openapi.codegen.python.rules import rules as python_codegen_rules
from pants.backend.openapi.sample.resources import PETSTORE_SAMPLE_SPEC
from pants.backend.openapi.target_types import (
    OpenApiDocumentDependenciesField,
    OpenApiDocumentField,
    OpenApiDocumentGeneratorTarget,
    OpenApiDocumentTarget,
    OpenApiSourceGeneratorTarget,
    OpenApiSourceTarget,
)
from pants.backend.openapi.target_types import rules as target_types_rules
from pants.backend.openapi.util_rules import openapi_bundle
from pants.backend.python.register import rules as python_backend_rules
from pants.engine.addresses import Address, Addresses
from pants.engine.target import (
    DependenciesRequest,
    GeneratedSources,
    HydratedSources,
    HydrateSourcesRequest,
)
from pants.testutil.rule_runner import PYTHON_BOOTSTRAP_ENV, QueryRule, RuleRunner

from pants.core.goals.test import rules as test_rules


@pytest.fixture
def rule_runner() -> RuleRunner:
    rule_runner = RuleRunner(
        target_types=[
            # *python_target_types(),
            OpenApiSourceTarget,
            OpenApiSourceGeneratorTarget,
            OpenApiDocumentTarget,
            OpenApiDocumentGeneratorTarget,
        ],
        rules=[
            *test_rules(),
            *config_files_rules(),
            *python_backend_rules(),
            *python_codegen_rules(),
            *openapi_bundle.rules(),
            *target_types_rules(),
            QueryRule(HydratedSources, (HydrateSourcesRequest,)),
            QueryRule(GeneratedSources, (GeneratePythonFromOpenAPIRequest,)),
            QueryRule(Addresses, (DependenciesRequest,)),
        ],
    )
    rule_runner.set_options(args=[], env_inherit=PYTHON_BOOTSTRAP_ENV)
    return rule_runner


def _assert_generated_files(
    rule_runner: RuleRunner,
    address: Address,
    *,
    expected_files: Iterable[str],
    source_roots: Iterable[str] | None = None,
    extra_args: Iterable[str] = (),
) -> None:
    args = []
    if source_roots:
        args.append(f"--source-root-patterns={repr(source_roots)}")
    args.extend(extra_args)
    rule_runner.set_options(args, env_inherit=PYTHON_BOOTSTRAP_ENV)

    tgt = rule_runner.get_target(address)
    protocol_sources = rule_runner.request(
        HydratedSources, [HydrateSourcesRequest(tgt[OpenApiDocumentField])]
    )
    generated_sources = rule_runner.request(
        GeneratedSources, [GeneratePythonFromOpenAPIRequest(protocol_sources.snapshot, tgt)]
    )

    # We only assert expected files are a subset of all generated since the generator creates a lot of support classes
    assert set(expected_files).intersection(generated_sources.snapshot.files) == set(expected_files)


def test_skip_generate_python(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "BUILD": "openapi_document(name='petstore', source='petstore_spec.yaml', skip_python=True)",
            "petstore_spec.yaml": PETSTORE_SAMPLE_SPEC,
        }
    )

    def assert_gen(address: Address, expected: Iterable[str]) -> None:
        _assert_generated_files(rule_runner, address, expected_files=expected)

    tgt_address = Address("", target_name="petstore")
    assert_gen(tgt_address, [])

    tgt = rule_runner.get_target(tgt_address)
    runtime_dependencies = rule_runner.request(
        Addresses, [DependenciesRequest(tgt[OpenApiDocumentDependenciesField])]
    )
    assert not runtime_dependencies


# def test_generate_python_sources(
#     rule_runner: RuleRunner, openapi_lockfile: PythonLockfileFixture
# ) -> None:
#     rule_runner.write_files(
#         {
#             "3rdparty/python/default.lock": openapi_lockfile.serialized_lockfile,
#             "3rdparty/python/BUILD": openapi_lockfile.requirements_as_python_artifact_targets(),
#             "src/openapi/BUILD": "openapi_document(name='petstore', source='petstore_spec.yaml')",
#             "src/openapi/petstore_spec.yaml": PETSTORE_SAMPLE_SPEC,
#         }
#     )
#
#     def assert_gen(address: Address, expected: Iterable[str]) -> None:
#         _assert_generated_files(
#             rule_runner, address, source_roots=["src/openapi"], expected_files=expected
#         )
#
#     tgt_address = Address("src/openapi", target_name="petstore")
#     assert_gen(
#         tgt_address,
#         [
#             "src/openapi/org/openapitools/client/api/PetsApi.python",
#             "src/openapi/org/openapitools/client/model/Pet.python",
#             "src/openapi/org/openapitools/client/model/Error.python",
#         ],
#     )
#
#     tgt = rule_runner.get_target(tgt_address)
#     runtime_dependencies = rule_runner.request(
#         Addresses, [DependenciesRequest(tgt[OpenApiDocumentDependenciesField])]
#     )
#     assert runtime_dependencies
#
#
# def test_generate_python_sources_using_custom_model_package(
#     rule_runner: RuleRunner, openapi_lockfile: PythonLockfileFixture
# ) -> None:
#     rule_runner.write_files(
#         {
#             "3rdparty/python/default.lock": openapi_lockfile.serialized_lockfile,
#             "3rdparty/python/BUILD": openapi_lockfile.requirements_as_python_artifact_targets(),
#             "src/openapi/BUILD": "openapi_document(name='petstore', source='petstore_spec.yaml', python_model_package='org.mycompany')",
#             "src/openapi/petstore_spec.yaml": PETSTORE_SAMPLE_SPEC,
#         }
#     )
#
#     def assert_gen(address: Address, expected: Iterable[str]) -> None:
#         _assert_generated_files(
#             rule_runner, address, source_roots=["src/openapi"], expected_files=expected
#         )
#
#     assert_gen(
#         Address("src/openapi", target_name="petstore"),
#         [
#             "src/openapi/org/mycompany/Pet.python",
#             "src/openapi/org/mycompany/Error.python",
#         ],
#     )
#
#
# def test_generate_python_sources_using_custom_api_package(
#     rule_runner: RuleRunner, openapi_lockfile: PythonLockfileFixture
# ) -> None:
#     rule_runner.write_files(
#         {
#             "3rdparty/python/default.lock": openapi_lockfile.serialized_lockfile,
#             "3rdparty/python/BUILD": openapi_lockfile.requirements_as_python_artifact_targets(),
#             "src/openapi/BUILD": "openapi_document(name='petstore', source='petstore_spec.yaml', python_api_package='org.mycompany')",
#             "src/openapi/petstore_spec.yaml": PETSTORE_SAMPLE_SPEC,
#         }
#     )
#
#     def assert_gen(address: Address, expected: Iterable[str]) -> None:
#         _assert_generated_files(
#             rule_runner, address, source_roots=["src/openapi"], expected_files=expected
#         )
#
#     assert_gen(
#         Address("src/openapi", target_name="petstore"),
#         [
#             "src/openapi/org/mycompany/PetsApi.python",
#         ],
#     )
#
#
# def test_python_dependency_inference(
#     rule_runner: RuleRunner, openapi_lockfile: PythonLockfileFixture
# ) -> None:
#     rule_runner.write_files(
#         {
#             "3rdparty/python/default.lock": openapi_lockfile.serialized_lockfile,
#             "3rdparty/python/BUILD": openapi_lockfile.requirements_as_python_artifact_targets(),
#             "src/openapi/BUILD": dedent(
#                 """\
#                 openapi_document(
#                     name="petstore",
#                     source="petstore_spec.yaml",
#                     python_api_package="org.mycompany.api",
#                     python_model_package="org.mycompany.model",
#                 )
#                 """
#             ),
#             "src/openapi/petstore_spec.yaml": PETSTORE_SAMPLE_SPEC,
#             "src/python/BUILD": "python_sources()",
#             "src/python/Example.python": dedent(
#                 """\
#                 package org.pantsbuild.python.example;
#
#                 import org.mycompany.api.PetsApi;
#                 import org.mycompany.model.Pet;
#
#                 public class Example {
#                     PetsApi api;
#                     Pet pet;
#                 }
#                 """
#             ),
#         }
#     )
#
#     tgt = rule_runner.get_target(Address("src/python", relative_file_path="Example.python"))
#     dependencies = rule_runner.request(Addresses, [DependenciesRequest(tgt[Dependencies])])
#     assert Address("src/openapi", target_name="petstore") in dependencies
