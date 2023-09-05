# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import pytest

from pants.backend.experimental.openapi.register import rules as target_types_rules
from pants.backend.javascript.subsystems import nodejs
from pants.backend.openapi.lint.openapi_format.rules import OpenApiFormatRequest
from pants.backend.openapi.lint.openapi_format.rules import rules as openapi_format_rules
from pants.backend.openapi.lint.openapi_format.subsystem import OpenApiFormatFieldSet
from pants.backend.openapi.target_types import OpenApiSourceGeneratorTarget
from pants.core.goals.fmt import FmtResult, Partitions
from pants.core.util_rules import config_files, stripped_source_files
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.engine.addresses import Address
from pants.engine.fs import PathGlobs
from pants.engine.internals.native_engine import Digest, Snapshot
from pants.engine.target import Target
from pants.testutil.rule_runner import QueryRule, RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *openapi_format_rules(),
            *config_files.rules(),
            *nodejs.rules(),
            *stripped_source_files.rules(),
            *target_types_rules(),
            QueryRule(Partitions, [OpenApiFormatRequest.PartitionRequest]),
            QueryRule(FmtResult, [OpenApiFormatRequest.Batch]),
            QueryRule(SourceFiles, (SourceFilesRequest,)),
        ],
        target_types=[OpenApiSourceGeneratorTarget],
    )


GOOD_FILE = "openapi: 3.0.0\ninfo:\n  title: Example\n  version: 1.0.0\npaths: {}\n"
BAD_FILE = "info:\n  title: Example\n  version: 1.0.0\npaths: {}\nopenapi: 3.0.0\n"


def run_openapi_format(
    rule_runner: RuleRunner,
    targets: list[Target],
    *,
    extra_args: list[str] | None = None,
) -> list[FmtResult]:
    rule_runner.set_options(
        [
            "--backend-packages=pants.backend.experimental.openapi.lint.openapi_format",
            *(extra_args or ()),
        ],
        env_inherit={"PATH"},
    )
    field_sets = [OpenApiFormatFieldSet.create(tgt) for tgt in targets]
    partitions = rule_runner.request(
        Partitions,
        [
            OpenApiFormatRequest.PartitionRequest(tuple(field_sets)),
        ],
    )

    results = []
    for partition in partitions:
        digest = rule_runner.request(Digest, [PathGlobs(partition.elements)])
        snapshot = rule_runner.request(Snapshot, [digest])
        result = rule_runner.request(
            FmtResult,
            [
                OpenApiFormatRequest.Batch(
                    "",
                    partition.elements,
                    partition_metadata=partition.metadata,
                    snapshot=snapshot,
                )
            ],
        )
        results.append(result)

    return results


def test_passing(rule_runner: RuleRunner) -> None:
    rule_runner.write_files({"openapi.yaml": GOOD_FILE, "BUILD": "openapi_sources(name='t')"})
    tgt = rule_runner.get_target(Address("", target_name="t", relative_file_path="openapi.yaml"))
    fmt_result = run_openapi_format(
        rule_runner,
        [tgt],
    )
    assert len(fmt_result) == 1
    assert "OpenAPI formatted successfully" in fmt_result[0].stderr
    assert fmt_result[0].output == rule_runner.make_snapshot({"openapi.yaml": GOOD_FILE})
    assert fmt_result[0].did_change is False


def test_failing(rule_runner: RuleRunner) -> None:
    rule_runner.write_files({"openapi.yaml": BAD_FILE, "BUILD": "openapi_sources(name='t')"})
    tgt = rule_runner.get_target(Address("", target_name="t", relative_file_path="openapi.yaml"))
    fmt_result = run_openapi_format(rule_runner, [tgt])
    assert len(fmt_result) == 1
    assert "OpenAPI formatted successfully" in fmt_result[0].stderr
    assert fmt_result[0].output == rule_runner.make_snapshot({"openapi.yaml": GOOD_FILE})
    assert fmt_result[0].did_change is True


def test_multiple_targets(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "bad.yaml": BAD_FILE,
            "good.yaml": GOOD_FILE,
            "BUILD": "openapi_sources(name='t', sources=['good.yaml', 'bad.yaml'])",
        }
    )
    tgts = [
        rule_runner.get_target(Address("", target_name="t", relative_file_path="bad.yaml")),
        rule_runner.get_target(Address("", target_name="t", relative_file_path="good.yaml")),
    ]
    fmt_result = run_openapi_format(rule_runner, tgts)
    assert len(fmt_result) == 2
    assert "OpenAPI formatted successfully" in fmt_result[0].stderr
    assert "OpenAPI formatted successfully" in fmt_result[1].stderr
    assert fmt_result[0].output == rule_runner.make_snapshot({"bad.yaml": GOOD_FILE})
    assert fmt_result[1].output == rule_runner.make_snapshot({"good.yaml": GOOD_FILE})
    assert fmt_result[0].did_change is True
    assert fmt_result[1].did_change is False


def test_passthrough_args(rule_runner: RuleRunner) -> None:
    rule_runner.write_files({"openapi.yaml": BAD_FILE, "BUILD": "openapi_sources(name='t')"})
    tgt = rule_runner.get_target(Address("", target_name="t", relative_file_path="openapi.yaml"))
    fmt_result = run_openapi_format(
        rule_runner, [tgt], extra_args=["--openapi-format-args='--no-sort'"]
    )
    assert len(fmt_result) == 1
    assert "OpenAPI formatted successfully" in fmt_result[0].stderr
    assert fmt_result[0].output == rule_runner.make_snapshot({"openapi.yaml": BAD_FILE})
    assert fmt_result[0].did_change is False


def test_skip(rule_runner: RuleRunner) -> None:
    rule_runner.write_files({"openapi.yaml": BAD_FILE, "BUILD": "openapi_sources(name='t')"})
    tgt = rule_runner.get_target(Address("", target_name="t", relative_file_path="openapi.yaml"))
    result = run_openapi_format(rule_runner, [tgt], extra_args=["--openapi-format-skip"])
    assert not result
