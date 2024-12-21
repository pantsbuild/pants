# Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from importlib import resources
from textwrap import dedent
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
from pants.backend.python.register import target_types as python_target_types
from pants.core.goals.test import rules as test_rules
from pants.core.util_rules.config_files import rules as config_files_rules
from pants.engine.addresses import Address, Addresses
from pants.engine.target import (
    Dependencies,
    DependenciesRequest,
    GeneratedSources,
    HydratedSources,
    HydrateSourcesRequest,
)
from pants.testutil.rule_runner import PYTHON_BOOTSTRAP_ENV, QueryRule, RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    rule_runner = RuleRunner(
        target_types=[
            *python_target_types(),
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
        GeneratedSources,
        [GeneratePythonFromOpenAPIRequest(protocol_sources.snapshot, tgt)],
    )

    # We only assert expected files are a subset of all generated since the generator creates a lot of support classes
    assert set(generated_sources.snapshot.files) == set(expected_files)


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


@pytest.fixture
def requirements_text() -> str:
    return dedent(
        """\
        python_requirement(
            name="urllib3",
            requirements=["urllib3"],
        )
        python_requirement(
            name="python-dateutil",
            requirements=["python-dateutil"],
        )
        python_requirement(
            name="setuptools",
            requirements=["setuptools"],
        )
    """
    )


def test_generate_python_sources(rule_runner: RuleRunner, requirements_text: str) -> None:
    rule_runner.write_files(
        {
            "3rdparty/python/default.lock": resources.files(__package__)
            .joinpath("openapi.test.lock")
            .read_text(),
            "3rdparty/python/BUILD": requirements_text,
            "src/openapi/BUILD": dedent(
                """\
                openapi_document(
                    name="petstore",
                    source="petstore_spec.yaml",
                    python_generator_name="python",
                )
            """
            ),
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
            # The list might change because it depends on openapi template.
            # TODO Vendor template?
            "src/openapi/openapi_client/__init__.py",
            "src/openapi/openapi_client/api/__init__.py",
            "src/openapi/openapi_client/api/pets_api.py",
            "src/openapi/openapi_client/api_client.py",
            "src/openapi/openapi_client/apis/__init__.py",
            "src/openapi/openapi_client/configuration.py",
            "src/openapi/openapi_client/exceptions.py",
            "src/openapi/openapi_client/model/__init__.py",
            "src/openapi/openapi_client/model/error.py",
            "src/openapi/openapi_client/model/pet.py",
            "src/openapi/openapi_client/model/pets.py",
            "src/openapi/openapi_client/model_utils.py",
            "src/openapi/openapi_client/models/__init__.py",
            "src/openapi/openapi_client/rest.py",
            "src/openapi/setup.py",
            "src/openapi/test/__init__.py",
            "src/openapi/test/test_error.py",
            "src/openapi/test/test_pet.py",
            "src/openapi/test/test_pets.py",
            "src/openapi/test/test_pets_api.py",
        ],
    )

    tgt = rule_runner.get_target(tgt_address)
    runtime_dependencies = rule_runner.request(
        Addresses, [DependenciesRequest(tgt[OpenApiDocumentDependenciesField])]
    )
    assert runtime_dependencies


@pytest.fixture
def fastapi_requirements_text() -> str:
    return dedent(
        """\
        python_requirement(name="jinja2", requirements=["jinja2"])
        python_requirement(name="markupsafe", requirements=["markupsafe"])
        python_requirement(name="pyyaml", requirements=["pyyaml"])
        python_requirement(name="rx", requirements=["rx"])
        python_requirement(name="aiofiles", requirements=["aiofiles"])
        python_requirement(name="aniso8601", requirements=["aniso8601"])
        python_requirement(name="async-exit-stack", requirements=["async-exit-stack"])
        python_requirement(name="async-generator", requirements=["async-generator"])
        python_requirement(name="certifi", requirements=["certifi"])
        python_requirement(name="chardet", requirements=["chardet"])
        python_requirement(name="click", requirements=["click"])
        python_requirement(name="dnspython", requirements=["dnspython"])
        python_requirement(name="email-validator", requirements=["email-validator"])
        python_requirement(name="fastapi", requirements=["fastapi"])
        python_requirement(name="graphene", requirements=["graphene"])
        python_requirement(name="graphql-core", requirements=["graphql-core"])
        python_requirement(name="graphql-relay", requirements=["graphql-relay"])
        python_requirement(name="h11", requirements=["h11"])
        python_requirement(name="httptools", requirements=["httptools"])
        python_requirement(name="idna", requirements=["idna"])
        python_requirement(name="itsdangerous", requirements=["itsdangerous"])
        python_requirement(name="orjson", requirements=["orjson"])
        python_requirement(name="promise", requirements=["promise"])
        python_requirement(name="pydantic", requirements=["pydantic"])
        python_requirement(name="python-dotenv", requirements=["python-dotenv"])
        python_requirement(name="python-multipart", requirements=["python-multipart"])
        python_requirement(name="requests", requirements=["requests"])
        python_requirement(name="six", requirements=["six"])
        python_requirement(name="starlette", requirements=["starlette"])
        python_requirement(name="typing-extensions", requirements=["typing-extensions"])
        python_requirement(name="ujson", requirements=["ujson"])
        python_requirement(name="urllib3", requirements=["urllib3"])
        python_requirement(name="uvicorn", requirements=["uvicorn"])
        python_requirement(name="uvloop", requirements=["uvloop"])
        python_requirement(name="watchgod", requirements=["watchgod"])
        python_requirement(name="websockets", requirements=["websockets"])
    """
    )


def test_generate_python_sources_with_a_different_generator(
    rule_runner: RuleRunner, fastapi_requirements_text: str
) -> None:
    rule_runner.write_files(
        {
            "3rdparty/python/default.lock": resources.files(__package__)
            .joinpath("openapi.test.lock")
            .read_text(),
            "3rdparty/python/BUILD": fastapi_requirements_text,
            "src/openapi/BUILD": dedent(
                """\
                openapi_document(
                    name="petstore",
                    source="petstore_spec.yaml",
                    python_generator_name="python-fastapi",
                )
            """
            ),
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
            # The list might change because it depends on openapi template.
            # TODO Vendor template?
            "src/openapi/src/openapi_server/apis/__init__.py",
            "src/openapi/src/openapi_server/apis/pets_api.py",
            "src/openapi/src/openapi_server/main.py",
            "src/openapi/src/openapi_server/models/__init__.py",
            "src/openapi/src/openapi_server/models/error.py",
            "src/openapi/src/openapi_server/models/extra_models.py",
            "src/openapi/src/openapi_server/models/pet.py",
            "src/openapi/src/openapi_server/security_api.py",
            "src/openapi/tests/conftest.py",
            "src/openapi/tests/test_pets_api.py",
        ],
    )

    tgt = rule_runner.get_target(tgt_address)
    runtime_dependencies = rule_runner.request(
        Addresses, [DependenciesRequest(tgt[OpenApiDocumentDependenciesField])]
    )
    assert runtime_dependencies


def test_generate_python_sources_using_custom_package_name(
    rule_runner: RuleRunner,
    requirements_text: str,
) -> None:
    rule_runner.write_files(
        {
            "3rdparty/python/default.lock": resources.files(__package__)
            .joinpath("openapi.test.lock")
            .read_text(),
            "3rdparty/python/BUILD": requirements_text,
            "src/openapi/BUILD": dedent(
                """\
                openapi_document(
                    name="petstore",
                    source="petstore_spec.yaml",
                    python_generator_name="python",
                    python_additional_properties={
                        "packageName": "petstore_client",
                    },
                )
            """
            ),
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
            # The list might change because it depends on openapi template.
            # TODO Vendor template?
            "src/openapi/petstore_client/__init__.py",
            "src/openapi/petstore_client/api/__init__.py",
            "src/openapi/petstore_client/api/pets_api.py",
            "src/openapi/petstore_client/api_client.py",
            "src/openapi/petstore_client/apis/__init__.py",
            "src/openapi/petstore_client/configuration.py",
            "src/openapi/petstore_client/exceptions.py",
            "src/openapi/petstore_client/model/__init__.py",
            "src/openapi/petstore_client/model/error.py",
            "src/openapi/petstore_client/model/pet.py",
            "src/openapi/petstore_client/model/pets.py",
            "src/openapi/petstore_client/model_utils.py",
            "src/openapi/petstore_client/models/__init__.py",
            "src/openapi/petstore_client/rest.py",
            "src/openapi/setup.py",
            "src/openapi/test/__init__.py",
            "src/openapi/test/test_error.py",
            "src/openapi/test/test_pet.py",
            "src/openapi/test/test_pets.py",
            "src/openapi/test/test_pets_api.py",
        ],
    )


def test_python_dependency_inference(rule_runner: RuleRunner, requirements_text: str) -> None:
    rule_runner.write_files(
        {
            "3rdparty/python/default.lock": resources.files(__package__)
            .joinpath("openapi.test.lock")
            .read_text(),
            "3rdparty/python/BUILD": requirements_text,
            "src/openapi/BUILD": dedent(
                """\
                openapi_document(
                    name="petstore",
                    source="petstore_spec.yaml",
                    python_generator_name="python",
                    python_additional_properties={
                        "packageName": "petstore_client",
                    },
                )
            """
            ),
            "src/openapi/petstore_spec.yaml": PETSTORE_SAMPLE_SPEC,
            "src/python/BUILD": "python_sources()",
            "src/python/example.py": dedent(
                """\
                from petstore_client.api_client import ApiClient
            """
            ),
        }
    )

    tgt = rule_runner.get_target(Address("src/python", relative_file_path="example.py"))
    dependencies = rule_runner.request(Addresses, [DependenciesRequest(tgt[Dependencies])])
    assert Address("src/openapi", target_name="petstore") in dependencies
