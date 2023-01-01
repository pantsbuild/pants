# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import textwrap
from typing import List, NewType

import pytest

from pants.backend.terraform import tool
from pants.backend.terraform.lint.tffmt import tffmt
from pants.backend.terraform.lint.tffmt.tffmt import TffmtRequest
from pants.backend.terraform.target_types import TerraformFieldSet, TerraformModuleTarget
from pants.backend.terraform.tool import TerraformTool
from pants.core.goals.fmt import FmtResult, Partitions
from pants.core.util_rules import external_tool, source_files
from pants.core.util_rules.external_tool import ExternalToolVersion
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.engine.addresses import Address
from pants.engine.fs import CreateDigest, Digest, DigestContents, FileContent
from pants.engine.internals.native_engine import Snapshot
from pants.engine.target import Target
from pants.testutil.rule_runner import QueryRule, RuleRunner

RuleRunnerOptions = NewType("RuleRunnerOptions", List[str])


available_tf_versions = [
    ExternalToolVersion.decode(v).version for v in TerraformTool.default_known_versions
]

tf_versions = [TerraformTool.default_version, available_tf_versions[0]]
# uncomment to run against *all* terraform versions
# tf_versions = list(set(available_tf_versions))


@pytest.fixture(params=tf_versions)
def rule_runner_options(request) -> RuleRunnerOptions:
    tf_version = request.param
    return RuleRunnerOptions(
        [
            "--backend-packages=pants.backend.experimental.terraform",
            "--backend-packages=pants.backend.experimental.terraform.lint.tffmt",
            f"--download-terraform-version={tf_version}",
        ]
    )


@pytest.fixture()
def rule_runner() -> RuleRunner:
    return RuleRunner(
        target_types=[TerraformModuleTarget],
        rules=[
            *external_tool.rules(),
            *tffmt.rules(),
            *tool.rules(),
            *source_files.rules(),
            QueryRule(Partitions, (TffmtRequest.PartitionRequest,)),
            QueryRule(FmtResult, (TffmtRequest.Batch,)),
            QueryRule(SourceFiles, (SourceFilesRequest,)),
        ],
    )


GOOD_SOURCE = FileContent(
    "good.tf",
    textwrap.dedent(
        """\
    locals {
      foo = "xyzzy"
    }

    resource "test_instance" "default" {
      key        = "value-${local.foo}"
      longer_key = "bar"
    }
    """
    ).encode("utf-8"),
)

# The misformatted part is the `key` property in the resource block.
BAD_SOURCE = FileContent(
    "bad.tf",
    textwrap.dedent(
        """\
    resource "test_instance" "default" {
      key = "foo"
      longer_key = "bar"
    }
    """
    ).encode("utf-8"),
)

FIXED_BAD_SOURCE = FileContent(
    "bad.tf",
    textwrap.dedent(
        """\
    resource "test_instance" "default" {
      key        = "foo"
      longer_key = "bar"
    }
    """
    ).encode("utf-8"),
)


def make_target(
    rule_runner: RuleRunner, source_files: List[FileContent], *, target_name="target"
) -> Target:
    rule_runner.write_files(
        {
            "BUILD": f"terraform_module(name='{target_name}')\n",
            **{source_file.path: source_file.content.decode() for source_file in source_files},
        }
    )
    return rule_runner.get_target(Address("", target_name=target_name))


def run_tffmt(
    rule_runner: RuleRunner,
    targets: List[Target],
    options: RuleRunnerOptions,
) -> FmtResult | None:
    rule_runner.set_options(options)
    field_sets = [TerraformFieldSet.create(tgt) for tgt in targets]
    input_sources = rule_runner.request(
        SourceFiles,
        [
            SourceFilesRequest(field_set.sources for field_set in field_sets),
        ],
    )
    partitions = rule_runner.request(
        Partitions,
        [
            TffmtRequest.PartitionRequest(tuple(field_sets)),
        ],
    )
    if not partitions:
        return None

    assert len(partitions) == 1
    partition = partitions[0]
    assert set(partition.elements) == set(input_sources.snapshot.files)
    fmt_result = rule_runner.request(
        FmtResult,
        [
            TffmtRequest.Batch(
                "",
                partition.elements,
                partition_metadata=partition.metadata,
                snapshot=input_sources.snapshot,
            ),
        ],
    )
    return fmt_result


def get_content(rule_runner: RuleRunner, digest: Digest) -> DigestContents:
    return rule_runner.request(DigestContents, [digest])


def get_snapshot(rule_runner: RuleRunner, source_files: List[FileContent]) -> Snapshot:
    digest = rule_runner.request(Digest, [CreateDigest(source_files)])
    return rule_runner.request(Snapshot, [digest])


def test_passing_source(rule_runner: RuleRunner, rule_runner_options: RuleRunnerOptions) -> None:
    target = make_target(rule_runner, [GOOD_SOURCE])
    fmt_result = run_tffmt(rule_runner, [target], rule_runner_options)
    assert fmt_result
    assert fmt_result.stdout == ""
    assert fmt_result.output == get_snapshot(rule_runner, [GOOD_SOURCE])
    assert fmt_result.did_change is False


def test_failing_source(rule_runner: RuleRunner, rule_runner_options: RuleRunnerOptions) -> None:
    target = make_target(rule_runner, [BAD_SOURCE])
    fmt_result = run_tffmt(rule_runner, [target], rule_runner_options)
    assert fmt_result
    contents = get_content(rule_runner, fmt_result.output.digest)
    print(f">>>{contents[0].content.decode()}<<<")
    assert fmt_result.stderr == ""
    assert fmt_result.output == get_snapshot(rule_runner, [FIXED_BAD_SOURCE])
    assert fmt_result.did_change is True


def test_mixed_sources(rule_runner: RuleRunner, rule_runner_options: RuleRunnerOptions) -> None:
    target = make_target(rule_runner, [GOOD_SOURCE, BAD_SOURCE])
    fmt_result = run_tffmt(rule_runner, [target], rule_runner_options)
    assert fmt_result
    assert fmt_result.output == get_snapshot(rule_runner, [GOOD_SOURCE, FIXED_BAD_SOURCE])
    assert fmt_result.did_change is True


def test_multiple_targets(rule_runner: RuleRunner, rule_runner_options: RuleRunnerOptions) -> None:
    targets = [
        make_target(rule_runner, [GOOD_SOURCE], target_name="tgt_good"),
        make_target(rule_runner, [BAD_SOURCE], target_name="tgt_bad"),
    ]
    fmt_result = run_tffmt(rule_runner, targets, rule_runner_options)
    assert fmt_result
    assert fmt_result.output == get_snapshot(rule_runner, [GOOD_SOURCE, FIXED_BAD_SOURCE])
    assert fmt_result.did_change is True


def test_skip(rule_runner: RuleRunner, rule_runner_options: RuleRunnerOptions) -> None:
    target = make_target(rule_runner, [BAD_SOURCE])

    rule_runner_options.append("--terraform-fmt-skip")  # skips running terraform

    fmt_result = run_tffmt(rule_runner, [target], rule_runner_options)
    assert fmt_result is None
