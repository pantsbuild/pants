# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import DefaultDict

import pytest

from pants.base.specs import RawSpecsWithoutFileOwners, RecursiveGlobSpec
from pants.core.target_types import FileTarget, GenericTarget
from pants.engine.addresses import Address, Addresses
from pants.engine.internals.specs_rules_test import resolve_raw_specs_without_file_owners
from pants.engine.internals.synthetic_targets import (
    SyntheticAddressMaps,
    SyntheticTargetsRequest,
    rules,
)
from pants.engine.internals.target_adaptor import TargetAdaptor
from pants.engine.rules import QueryRule, rule
from pants.engine.target import (
    DescriptionField,
    InvalidTargetException,
    Tags,
    WrappedTarget,
    WrappedTargetRequest,
)
from pants.engine.unions import UnionRule
from pants.testutil.rule_runner import RuleRunner, engine_error
from pants.util.strutil import softwrap


@dataclass(frozen=True)
class SyntheticExampleTargetsRequest(SyntheticTargetsRequest):
    path: str = SyntheticTargetsRequest.SINGLE_REQUEST_FOR_ALL_TARGETS


@dataclass(frozen=True)
class SyntheticExampleTargetsPerDirectoryRequest(SyntheticTargetsRequest):
    path: str = SyntheticTargetsRequest.REQUEST_TARGETS_PER_DIRECTORY


@rule
async def example_synthetic_targets(
    request: SyntheticExampleTargetsRequest,
) -> SyntheticAddressMaps:
    assert request.path == SyntheticTargetsRequest.SINGLE_REQUEST_FOR_ALL_TARGETS
    targets = [
        (
            "src/test/BUILD.test",
            (
                TargetAdaptor(
                    "target",
                    "generic1",
                    description="Target 1",
                ),
                TargetAdaptor(
                    "target",
                    "generic2",
                    description="Target 2",
                    tags=["synthetic", "tags"],
                ),
            ),
        ),
        (
            "src/synthetic/BUILD.synthetic",
            (TargetAdaptor("target", "generic-synth", description="Additional target"),),
        ),
    ]
    return SyntheticAddressMaps.for_targets_request(request, targets)


example_synthetic_targets_per_directory_counts: DefaultDict[str, int] = defaultdict(int)


@rule
async def example_synthetic_targets_per_directory(
    request: SyntheticExampleTargetsPerDirectoryRequest,
) -> SyntheticAddressMaps:
    assert request.path != SyntheticTargetsRequest.SINGLE_REQUEST_FOR_ALL_TARGETS
    example_synthetic_targets_per_directory_counts[request.path] += 1
    targets = {
        "src/test": [
            (
                "src/test/BUILD.dir-a",
                (
                    TargetAdaptor(
                        "target",
                        "generic3",
                        description="Target 3",
                    ),
                ),
            ),
            (
                "src/test/BUILD.dir-b",
                (
                    TargetAdaptor(
                        "target",
                        "generic4",
                        description="Target 4",
                        tags=["synthetic", "tags"],
                    ),
                ),
            ),
        ],
    }
    return SyntheticAddressMaps.for_targets_request(request, targets.get(request.path, ()))


@pytest.fixture
def rule_runner() -> RuleRunner:
    rule_runner = RuleRunner(
        rules=[
            *rules(),
            example_synthetic_targets,
            example_synthetic_targets_per_directory,
            *SyntheticExampleTargetsRequest.rules(),
            *SyntheticExampleTargetsPerDirectoryRequest.rules(),
            QueryRule(Addresses, [RawSpecsWithoutFileOwners]),
        ],
        target_types=[GenericTarget, FileTarget],
    )
    return rule_runner


def assert_target(
    rule_runner: RuleRunner, name: str, description: str | None = None, tags: tuple | None = None
) -> None:
    tgt = rule_runner.request(
        WrappedTarget,
        [WrappedTargetRequest(Address("src/test", target_name=name), "synth test")],
    ).target
    assert tgt.alias == "target"
    assert tgt.address.target_name == name
    assert tgt[DescriptionField].value == description
    assert tgt[Tags].value == tags


def test_register_synthetic_targets(rule_runner: RuleRunner) -> None:
    example_synthetic_targets_per_directory_counts.clear()
    assert_target(rule_runner, name="generic1", description="Target 1")
    assert_target(rule_runner, name="generic2", description="Target 2", tags=("synthetic", "tags"))
    assert_target(rule_runner, name="generic3", description="Target 3")
    assert_target(rule_runner, name="generic4", description="Target 4", tags=("synthetic", "tags"))
    assert example_synthetic_targets_per_directory_counts == {".": 1, "src": 1, "src/test": 1}


def test_override_synthetic_targets(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "src/test/BUILD": """target(name="generic2", description="from BUILD file")""",
        }
    )

    assert_target(rule_runner, name="generic2", description="from BUILD file")


def test_extend_synthetic_targets(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "src/test/BUILD": """target(name="generic2", description="from BUILD file", _extend_synthetic=True)""",
        }
    )

    assert_target(
        rule_runner, name="generic2", description="from BUILD file", tags=("synthetic", "tags")
    )


def test_synthetic_targets_with_defaults(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "src/test/BUILD": """__defaults__(dict(target=dict(tags=["default", "4real"])))""",
        }
    )

    assert_target(rule_runner, name="generic1", description="Target 1", tags=("default", "4real"))


def test_override_synthetic_targets_wrong_type(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "src/test/BUILD": """file(name="generic1", source="BUILD", _extend_synthetic=True)""",
        }
    )

    err = softwrap(
        """
        The `file` target 'generic1' in src/test/BUILD is of a different type than the synthetic
        target `target` from src/test/BUILD.test.

        When `_extend_synthetic` is true the target types must match, set this to false if you want
        to replace the synthetic target with the target from your BUILD file.
        """
    )

    with engine_error(InvalidTargetException, contains=err):
        rule_runner.request(
            WrappedTarget,
            [WrappedTargetRequest(Address("src/test", target_name="generic1"), "synth test")],
        )


def test_extend_missing_synthetic_target(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "src/test/BUILD": """target(name="another", _extend_synthetic=True)""",
        }
    )

    err = softwrap(
        """
        The `target` target 'another' in src/test/BUILD has `_extend_synthetic=True` but there is no
        synthetic target to extend.
        """
    )

    with engine_error(InvalidTargetException, contains=err.strip()):
        rule_runner.request(
            WrappedTarget,
            [WrappedTargetRequest(Address("src/test", target_name="another"), "synth test")],
        )


def test_additional_spec_path(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "src/BUILD": "",
        }
    )
    assert Address(
        "src/synthetic", target_name="generic-synth"
    ) in resolve_raw_specs_without_file_owners(rule_runner, [RecursiveGlobSpec("src")])
