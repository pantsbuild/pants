# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from typing import Iterable

import pytest

from pants.backend.openapi.codegen.java.rules import GenerateJavaFromOpenAPIRequest
from pants.backend.openapi.codegen.java.rules import rules as java_codegen_rules
from pants.backend.openapi.target_types import (
    OpenApiSourceField,
    OpenApiSourceGeneratorTarget,
    OpenApiSourceTarget,
)
from pants.backend.openapi.testutils.resources import PETSTORE_SAMPLE_SPEC
from pants.core.util_rules import config_files, external_tool, source_files, system_binaries
from pants.engine.addresses import Address
from pants.engine.target import GeneratedSources, HydratedSources, HydrateSourcesRequest
from pants.jvm.testutil import maybe_skip_jdk_test
from pants.testutil.rule_runner import PYTHON_BOOTSTRAP_ENV, QueryRule, RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    rule_runner = RuleRunner(
        target_types=[OpenApiSourceTarget, OpenApiSourceGeneratorTarget],
        rules=[
            *java_codegen_rules(),
            *config_files.rules(),
            *source_files.rules(),
            *external_tool.rules(),
            *system_binaries.rules(),
            QueryRule(HydratedSources, (HydrateSourcesRequest,)),
            QueryRule(GeneratedSources, (GenerateJavaFromOpenAPIRequest,)),
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
        HydratedSources, [HydrateSourcesRequest(tgt[OpenApiSourceField])]
    )
    generated_sources = rule_runner.request(
        GeneratedSources, [GenerateJavaFromOpenAPIRequest(protocol_sources.snapshot, tgt)]
    )

    # We only assert expected files are a subset of all generated since the generator creates a lot of support classes
    assert set(expected_files).intersection(generated_sources.snapshot.files) == set(expected_files)


@maybe_skip_jdk_test
def test_skip_generate_java(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "BUILD": "openapi_source(name='petstore', source='petstore_spec.yaml', skip_java=True)",
            "petstore_spec.yaml": PETSTORE_SAMPLE_SPEC,
        }
    )

    def assert_gen(address: Address, expected: Iterable[str]) -> None:
        _assert_generated_files(rule_runner, address, expected_files=expected)

    assert_gen(Address("", target_name="petstore"), [])


@maybe_skip_jdk_test
def test_generate_java_sources(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "BUILD": "openapi_source(name='petstore', source='petstore_spec.yaml')",
            "petstore_spec.yaml": PETSTORE_SAMPLE_SPEC,
        }
    )

    def assert_gen(address: Address, expected: Iterable[str]) -> None:
        _assert_generated_files(rule_runner, address, expected_files=expected)

    assert_gen(
        Address("", target_name="petstore"),
        [
            "org/openapitools/client/api/PetsApi.java",
            "org/openapitools/client/model/Pet.java",
            "org/openapitools/client/model/Error.java",
        ],
    )


@maybe_skip_jdk_test
def test_generate_java_sources_using_custom_model_package(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "BUILD": "openapi_source(name='petstore', source='petstore_spec.yaml', java_model_package='org.mycompany')",
            "petstore_spec.yaml": PETSTORE_SAMPLE_SPEC,
        }
    )

    def assert_gen(address: Address, expected: Iterable[str]) -> None:
        _assert_generated_files(rule_runner, address, expected_files=expected)

    assert_gen(
        Address("", target_name="petstore"),
        [
            "org/mycompany/Pet.java",
            "org/mycompany/Error.java",
        ],
    )


@maybe_skip_jdk_test
def test_generate_java_sources_using_custom_api_package(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "BUILD": "openapi_source(name='petstore', source='petstore_spec.yaml', java_api_package='org.mycompany')",
            "petstore_spec.yaml": PETSTORE_SAMPLE_SPEC,
        }
    )

    def assert_gen(address: Address, expected: Iterable[str]) -> None:
        _assert_generated_files(rule_runner, address, expected_files=expected)

    assert_gen(
        Address("", target_name="petstore"),
        [
            "org/mycompany/PetsApi.java",
        ],
    )
