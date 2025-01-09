# Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import textwrap

import pytest

from pants.backend.openapi import dependency_inference
from pants.backend.openapi.subsystems.redocly import Redocly
from pants.backend.openapi.target_types import (
    OpenApiBundleTarget,
    OpenApiDocumentGeneratorTarget,
    OpenApiSourceGeneratorTarget,
)
from pants.backend.openapi.target_types import rules as target_types_rules
from pants.backend.openapi.util_rules.openapi_bundle import GenerateOpenApiBundleRequest
from pants.backend.openapi.util_rules.openapi_bundle import rules as openapi_bundle_rules
from pants.core.util_rules import stripped_source_files
from pants.engine.addresses import Address
from pants.engine.fs import EMPTY_SNAPSHOT, DigestContents
from pants.engine.target import GeneratedSources
from pants.testutil.rule_runner import QueryRule, RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *target_types_rules(),
            *openapi_bundle_rules(),
            *dependency_inference.rules(),
            *stripped_source_files.rules(),
            QueryRule(GeneratedSources, [GenerateOpenApiBundleRequest, Redocly]),
        ],
        target_types=[
            OpenApiSourceGeneratorTarget,
            OpenApiDocumentGeneratorTarget,
            OpenApiBundleTarget,
        ],
    )


def assert_files_generated(
    rule_runner: RuleRunner,
    address: Address,
    *,
    expected_files: dict[str, bytes],
    source_roots: list[str],
    extra_args: list[str] | None = None,
) -> None:
    args = [
        f"--source-root-patterns={repr(source_roots)}",
        *(extra_args or ()),
    ]
    rule_runner.set_options(args, env_inherit={"PATH", "PYENV_ROOT", "HOME"})
    tgt = rule_runner.get_target(address)

    generated_sources = rule_runner.request(
        GeneratedSources,
        [GenerateOpenApiBundleRequest(EMPTY_SNAPSHOT, tgt)],
    )

    assert set(generated_sources.snapshot.files) == set(expected_files.keys())

    generated_sources_contents = rule_runner.request(
        DigestContents, [generated_sources.snapshot.digest]
    )

    for file_content in generated_sources_contents:
        assert file_content.content == expected_files[file_content.path]


def test_bundle(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "src/openapi/foo/BUILD": textwrap.dedent(
                """\
                openapi_sources()

                openapi_documents(name="openapi")

                openapi_bundle(name="bundle", dependencies=[":openapi"])
                """
            ),
            "src/openapi/foo/openapi.json": textwrap.dedent(
                """\
            {
              "openapi": "3.0.0",
              "components": {
                "schemas": {
                  "$ref": "bar/models.json"
                }
              }
            }"""
            ),
            "src/openapi/foo/bar/BUILD": "openapi_sources()\n",
            "src/openapi/foo/bar/models.json": '{"bar": "baz"}\n',
        }
    )

    assert_files_generated(
        rule_runner,
        Address("src/openapi/foo", target_name="bundle"),
        source_roots=["src/openapi"],
        expected_files={
            "src/openapi/foo/openapi.json": textwrap.dedent(
                """\
            {
              "openapi": "3.0.0",
              "components": {
                "schemas": {
                  "bar": "baz"
                }
              }
            }"""
            ).encode(),
        },
    )


def test_bundle_with_source_root(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "src/openapi/foo/BUILD": textwrap.dedent(
                """\
                openapi_sources()
                openapi_documents(name="openapi")

                openapi_bundle(
                  name="bundle",
                  bundle_source_root="src/python",
                  dependencies=[":openapi"],
                )
                """
            ),
            "src/openapi/foo/openapi.json": textwrap.dedent(
                """\
            {
              "openapi": "3.0.0",
              "components": {
                "schemas": {
                  "$ref": "bar/models.json"
                }
              }
            }"""
            ),
            "src/openapi/foo/bar/BUILD": "openapi_sources()\n",
            "src/openapi/foo/bar/models.json": '{"bar": "baz"}\n',
        }
    )

    assert_files_generated(
        rule_runner,
        Address("src/openapi/foo", target_name="bundle"),
        source_roots=["src/openapi", "src/python"],
        expected_files={
            "src/python/foo/openapi.json": textwrap.dedent(
                """\
            {
              "openapi": "3.0.0",
              "components": {
                "schemas": {
                  "bar": "baz"
                }
              }
            }"""
            ).encode(),
        },
    )
