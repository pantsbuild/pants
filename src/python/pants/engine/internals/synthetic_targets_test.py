# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import functools
from collections import defaultdict
from dataclasses import dataclass
from textwrap import dedent
from typing import DefaultDict

import pytest

from pants.backend.python.macros import python_requirements
from pants.backend.python.macros.python_requirements import PythonRequirementsTargetGenerator
from pants.base.specs import RawSpecsWithoutFileOwners, RecursiveGlobSpec
from pants.core.target_types import FileTarget, GenericTarget, LockfilesGeneratorTarget
from pants.engine.addresses import Address, Addresses
from pants.engine.environment import EnvironmentName
from pants.engine.internals.synthetic_targets import (
    SyntheticAddressMaps,
    SyntheticTargetsRequest,
    SyntheticTargetsSpecPaths,
    rules,
)
from pants.engine.internals.target_adaptor import TargetAdaptor as _TargetAdaptor
from pants.engine.internals.testutil import resolve_raw_specs_without_file_owners
from pants.engine.rules import QueryRule, rule
from pants.engine.target import (
    Dependencies,
    DependenciesRequest,
    DescriptionField,
    InvalidTargetException,
    Tags,
    Target,
    WrappedTarget,
    WrappedTargetRequest,
)
from pants.testutil.rule_runner import RuleRunner, engine_error
from pants.util.strutil import softwrap

TargetAdaptor = functools.partial(_TargetAdaptor, __description_of_origin__="BUILD")


@dataclass(frozen=True)
class SyntheticExampleTargetsRequest(SyntheticTargetsRequest):
    path: str = SyntheticTargetsRequest.SINGLE_REQUEST_FOR_ALL_TARGETS


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


class SyntheticExampleTargetsPerDirectorySpecPathsRequest:
    pass


@dataclass(frozen=True)
class SyntheticExampleTargetsPerDirectoryRequest(SyntheticTargetsRequest):
    path: str = SyntheticTargetsRequest.REQUEST_TARGETS_PER_DIRECTORY
    spec_paths_request = SyntheticExampleTargetsPerDirectorySpecPathsRequest


example_synthetic_targets_per_directory_counts: DefaultDict[str, int] = defaultdict(int)
example_synthetic_targets_per_directory_targets = {
    "src/test": [
        (
            "BUILD.dir-a",
            (
                TargetAdaptor(
                    "target",
                    "generic3",
                    description="Target 3",
                ),
            ),
        ),
        (
            "BUILD.dir-b",
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
    "src/issues/17343": [
        (
            "BUILD.issue",
            (
                TargetAdaptor(
                    "_lockfiles",
                    "python-default",
                    sources=["lockfile"],
                ),
            ),
        ),
    ],
    "src/bare/tree": [
        (
            "BUILD.synthetic-targets",
            (TargetAdaptor("target", "bare-tree"),),
        ),
    ],
}


@rule
def example_synthetic_targets_per_directory_spec_paths(
    request: SyntheticExampleTargetsPerDirectorySpecPathsRequest,
) -> SyntheticTargetsSpecPaths:
    # Return all paths we have targets for.
    return SyntheticTargetsSpecPaths.from_paths(example_synthetic_targets_per_directory_targets)


@rule
async def example_synthetic_targets_per_directory(
    request: SyntheticExampleTargetsPerDirectoryRequest,
) -> SyntheticAddressMaps:
    assert request.path != SyntheticTargetsRequest.SINGLE_REQUEST_FOR_ALL_TARGETS
    example_synthetic_targets_per_directory_counts[request.path] += 1
    targets = example_synthetic_targets_per_directory_targets.get(request.path, ())
    return SyntheticAddressMaps.for_targets_request(request, targets)


@pytest.fixture
def rule_runner() -> RuleRunner:
    rule_runner = RuleRunner(
        rules=[
            *rules(),
            *python_requirements.rules(),
            *SyntheticExampleTargetsRequest.rules(),
            *SyntheticExampleTargetsPerDirectoryRequest.rules(),
            example_synthetic_targets,
            example_synthetic_targets_per_directory,
            example_synthetic_targets_per_directory_spec_paths,
            QueryRule(Addresses, [RawSpecsWithoutFileOwners]),
            QueryRule(Addresses, (DependenciesRequest, EnvironmentName)),
        ],
        target_types=[
            FileTarget,
            GenericTarget,
            LockfilesGeneratorTarget,
            PythonRequirementsTargetGenerator,
        ],
    )
    return rule_runner


def assert_target(
    rule_runner: RuleRunner,
    name_or_address: str | Address,
    alias: str = "target",
    description: str | None = None,
    tags: tuple | None = None,
) -> Target:
    if isinstance(name_or_address, str):
        address = Address("src/test", target_name=name_or_address)
    elif isinstance(name_or_address, Address):
        address = name_or_address

    tgt = rule_runner.request(
        WrappedTarget,
        [WrappedTargetRequest(address, "synth test")],
    ).target
    assert tgt.alias == alias
    assert tgt.address.target_name == address.target_name
    assert tgt[DescriptionField].value == description
    assert tgt[Tags].value == tags
    return tgt


def test_register_synthetic_targets(rule_runner: RuleRunner) -> None:
    example_synthetic_targets_per_directory_counts.clear()
    assert_target(rule_runner, "generic1", description="Target 1")
    assert_target(rule_runner, "generic2", description="Target 2", tags=("synthetic", "tags"))
    assert_target(rule_runner, "generic3", description="Target 3")
    assert_target(rule_runner, "generic4", description="Target 4", tags=("synthetic", "tags"))
    assert example_synthetic_targets_per_directory_counts == {".": 1, "src": 1, "src/test": 1}


def test_override_synthetic_targets(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "src/test/BUILD": """target(name="generic2", description="from BUILD file")""",
        }
    )

    assert_target(rule_runner, "generic2", description="from BUILD file")


def test_extend_synthetic_targets(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "src/test/BUILD": """target(name="generic2", description="from BUILD file", _extend_synthetic=True)""",
        }
    )

    assert_target(
        rule_runner, "generic2", description="from BUILD file", tags=("synthetic", "tags")
    )


def test_synthetic_targets_with_defaults(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "src/test/BUILD": """__defaults__(dict(target=dict(tags=["default", "4real"])))""",
        }
    )

    assert_target(rule_runner, "generic1", description="Target 1", tags=("default", "4real"))


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
            # We need this to avoid:
            # Exception: Unmatched glob from tests: "src/**"
            "src/BUILD": "",
        }
    )
    addresses = resolve_raw_specs_without_file_owners(rule_runner, [RecursiveGlobSpec("src")])
    assert Address("src/synthetic", target_name="generic-synth") in addresses
    assert Address("src/bare/tree", target_name="bare-tree") in addresses


def test_target_name_collision_issue_17343(rule_runner: RuleRunner) -> None:
    # The issue was that the synthesized _lockfiles target is replaced by the python_requirements
    # target with the same name so the injected dependency pointed to itself rather than the
    # lockfile.
    rule_runner.set_options(
        [
            "--python-enable-resolves",
            "--python-resolves={'python-default': 'src/issues/17343/lockfile'}",
        ],
    )
    rule_runner.write_files(
        {
            "src/issues/17343/BUILD": softwrap(
                """
                python_requirements(
                  name="_python-default_lockfile",
                  overrides={
                    "humbug": {
                      "dependencies": ["_python-default_lockfile#setuptools"],
                    },
                  },
                )
                """
            ),
            "src/issues/17343/lockfile": "lockfile content",
            "src/issues/17343/requirements.txt": dedent(
                """\
                humbug
                setuptools
                """
            ),
        }
    )

    tgt = assert_target(
        rule_runner,
        Address(
            "src/issues/17343", target_name="_python-default_lockfile", generated_name="setuptools"
        ),
        alias="python_requirement",
    )

    # This should just work, as the `python_requirements` has the same target name as the synthetic
    # _lockfiles target, the synthetic target will be replaced. The fix for #17343 is that there
    # shouldn't be a dependency added to the python_requirements target on the _lockfile as it won't
    # exist.
    addresses = rule_runner.request(Addresses, [DependenciesRequest(tgt[Dependencies])])
    assert addresses
