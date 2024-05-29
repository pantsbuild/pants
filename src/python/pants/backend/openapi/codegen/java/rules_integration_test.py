# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from textwrap import dedent
from typing import Iterable

import pytest

from internal_plugins.test_lockfile_fixtures.lockfile_fixture import (
    JVMLockfileFixture,
    JVMLockfileFixtureDefinition,
)
from pants.backend.experimental.java.register import rules as java_backend_rules
from pants.backend.java.compile.javac import CompileJavaSourceRequest
from pants.backend.java.target_types import JavaSourcesGeneratorTarget, JavaSourceTarget
from pants.backend.openapi.codegen.java.rules import GenerateJavaFromOpenAPIRequest
from pants.backend.openapi.codegen.java.rules import rules as java_codegen_rules
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
from pants.engine.addresses import Address, Addresses
from pants.engine.target import (
    Dependencies,
    DependenciesRequest,
    GeneratedSources,
    HydratedSources,
    HydrateSourcesRequest,
)
from pants.jvm import testutil
from pants.jvm.target_types import JvmArtifactTarget
from pants.jvm.testutil import (
    RenderedClasspath,
    expect_single_expanded_coarsened_target,
    make_resolve,
    maybe_skip_jdk_test,
)
from pants.testutil.rule_runner import PYTHON_BOOTSTRAP_ENV, QueryRule, RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    rule_runner = RuleRunner(
        target_types=[
            JvmArtifactTarget,
            JavaSourceTarget,
            JavaSourcesGeneratorTarget,
            OpenApiSourceTarget,
            OpenApiSourceGeneratorTarget,
            OpenApiDocumentTarget,
            OpenApiDocumentGeneratorTarget,
        ],
        rules=[
            *java_backend_rules(),
            *java_codegen_rules(),
            *openapi_bundle.rules(),
            *target_types_rules(),
            *testutil.rules(),
            QueryRule(HydratedSources, (HydrateSourcesRequest,)),
            QueryRule(GeneratedSources, (GenerateJavaFromOpenAPIRequest,)),
            QueryRule(Addresses, (DependenciesRequest,)),
            QueryRule(RenderedClasspath, (CompileJavaSourceRequest,)),
        ],
    )
    rule_runner.set_options(args=[], env_inherit=PYTHON_BOOTSTRAP_ENV)
    return rule_runner


@pytest.fixture
def openapi_lockfile_def() -> JVMLockfileFixtureDefinition:
    return JVMLockfileFixtureDefinition(
        "openapi.test.lock",
        [
            "org.apache.commons:commons-lang3:3.12.0",
            "io.swagger:swagger-annotations:1.6.3",
            "com.squareup.okhttp3:okhttp:4.9.2",
            "com.google.code.findbugs:jsr305:3.0.2",
            "io.gsonfire:gson-fire:1.8.5",
            "org.openapitools:jackson-databind-nullable:0.2.2",
            "com.squareup.okhttp3:logging-interceptor:4.9.2",
            "jakarta.annotation:jakarta.annotation-api:1.3.5",
            "com.google.code.gson:gson:2.8.8",
            "org.threeten:threetenbp:1.5.0",
        ],
    )


@pytest.fixture
def openapi_lockfile(
    openapi_lockfile_def: JVMLockfileFixtureDefinition, request
) -> JVMLockfileFixture:
    return openapi_lockfile_def.load(request)


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
        GeneratedSources, [GenerateJavaFromOpenAPIRequest(protocol_sources.snapshot, tgt)]
    )

    # We only assert expected files are a subset of all generated since the generator creates a lot of support classes
    assert set(expected_files).intersection(generated_sources.snapshot.files) == set(expected_files)


@maybe_skip_jdk_test
def test_skip_generate_java(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "BUILD": "openapi_document(name='petstore', source='petstore_spec.yaml', skip_java=True)",
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


@maybe_skip_jdk_test
def test_generate_java_sources(
    rule_runner: RuleRunner, openapi_lockfile: JVMLockfileFixture
) -> None:
    rule_runner.write_files(
        {
            "3rdparty/jvm/default.lock": openapi_lockfile.serialized_lockfile,
            "3rdparty/jvm/BUILD": openapi_lockfile.requirements_as_jvm_artifact_targets(),
            "src/openapi/BUILD": "openapi_document(name='petstore', source='petstore_spec.yaml')",
            "src/openapi/petstore_spec.yaml": PETSTORE_SAMPLE_SPEC,
        }
    )

    def assert_gen(address: Address, expected: Iterable[str]) -> None:
        _assert_generated_files(
            rule_runner, address, source_roots=["src/openapi"], expected_files=expected
        )

    tgt_address = Address("src/openapi", target_name="petstore")
    assert_gen(
        tgt_address,
        [
            "src/openapi/org/openapitools/client/api/PetsApi.java",
            "src/openapi/org/openapitools/client/model/Pet.java",
            "src/openapi/org/openapitools/client/model/Error.java",
        ],
    )

    tgt = rule_runner.get_target(tgt_address)
    runtime_dependencies = rule_runner.request(
        Addresses, [DependenciesRequest(tgt[OpenApiDocumentDependenciesField])]
    )
    assert runtime_dependencies


@maybe_skip_jdk_test
def test_generate_java_sources_using_custom_model_package(
    rule_runner: RuleRunner, openapi_lockfile: JVMLockfileFixture
) -> None:
    rule_runner.write_files(
        {
            "3rdparty/jvm/default.lock": openapi_lockfile.serialized_lockfile,
            "3rdparty/jvm/BUILD": openapi_lockfile.requirements_as_jvm_artifact_targets(),
            "src/openapi/BUILD": "openapi_document(name='petstore', source='petstore_spec.yaml', java_model_package='org.mycompany')",
            "src/openapi/petstore_spec.yaml": PETSTORE_SAMPLE_SPEC,
        }
    )

    def assert_gen(address: Address, expected: Iterable[str]) -> None:
        _assert_generated_files(
            rule_runner, address, source_roots=["src/openapi"], expected_files=expected
        )

    assert_gen(
        Address("src/openapi", target_name="petstore"),
        [
            "src/openapi/org/mycompany/Pet.java",
            "src/openapi/org/mycompany/Error.java",
        ],
    )


@maybe_skip_jdk_test
def test_generate_java_sources_using_custom_api_package(
    rule_runner: RuleRunner, openapi_lockfile: JVMLockfileFixture
) -> None:
    rule_runner.write_files(
        {
            "3rdparty/jvm/default.lock": openapi_lockfile.serialized_lockfile,
            "3rdparty/jvm/BUILD": openapi_lockfile.requirements_as_jvm_artifact_targets(),
            "src/openapi/BUILD": "openapi_document(name='petstore', source='petstore_spec.yaml', java_api_package='org.mycompany')",
            "src/openapi/petstore_spec.yaml": PETSTORE_SAMPLE_SPEC,
        }
    )

    def assert_gen(address: Address, expected: Iterable[str]) -> None:
        _assert_generated_files(
            rule_runner, address, source_roots=["src/openapi"], expected_files=expected
        )

    assert_gen(
        Address("src/openapi", target_name="petstore"),
        [
            "src/openapi/org/mycompany/PetsApi.java",
        ],
    )


@maybe_skip_jdk_test
def test_java_dependency_inference(
    rule_runner: RuleRunner, openapi_lockfile: JVMLockfileFixture
) -> None:
    rule_runner.write_files(
        {
            "3rdparty/jvm/default.lock": openapi_lockfile.serialized_lockfile,
            "3rdparty/jvm/BUILD": openapi_lockfile.requirements_as_jvm_artifact_targets(),
            "src/openapi/BUILD": dedent(
                """\
                openapi_document(
                    name="petstore",
                    source="petstore_spec.yaml",
                    java_api_package="org.mycompany.api",
                    java_model_package="org.mycompany.model",
                )
                """
            ),
            "src/openapi/petstore_spec.yaml": PETSTORE_SAMPLE_SPEC,
            "src/java/BUILD": "java_sources()",
            "src/java/Example.java": dedent(
                """\
                package org.pantsbuild.java.example;

                import org.mycompany.api.PetsApi;
                import org.mycompany.model.Pet;

                public class Example {
                    PetsApi api;
                    Pet pet;
                }
                """
            ),
        }
    )

    tgt = rule_runner.get_target(Address("src/java", relative_file_path="Example.java"))
    dependencies = rule_runner.request(Addresses, [DependenciesRequest(tgt[Dependencies])])
    assert Address("src/openapi", target_name="petstore") in dependencies

    coarsened_target = expect_single_expanded_coarsened_target(
        rule_runner, Address(spec_path="src/java")
    )
    _ = rule_runner.request(
        RenderedClasspath,
        [CompileJavaSourceRequest(component=coarsened_target, resolve=make_resolve(rule_runner))],
    )
