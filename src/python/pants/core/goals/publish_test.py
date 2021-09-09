# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from typing import Iterable, List, Optional, Type

import pytest

from pants.build_graph.address import Address
from pants.core.goals.package import BuiltPackage, PackageFieldSet
from pants.core.goals.publish import (
    Publish,
    PublishedPackage,
    PublishRequest,
    PublishTarget,
    PublishTargetField,
    publish,
)
from pants.engine.addresses import UnparsedAddressInputs
from pants.engine.target import Sources, Target, Targets
from pants.engine.unions import UnionMembership
from pants.testutil.rule_runner import MockGet, RuleRunner, mock_console, run_rule_with_mocks


class MockTarget(Target):
    alias = "mock_target"
    core_fields = (Sources, PublishTargetField)


class MockTargetPackageFieldSet(PackageFieldSet):
    required_fields = (Sources,)


class MockPublishRequest(PublishRequest):
    pass


class MockPublishTarget(PublishTarget):
    alias = "mock_publish_target"
    publish_request_type = MockPublishRequest


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner()


def make_target(
    address: Optional[Address] = None,
    publish_targets: Optional[Iterable[PublishTarget]] = (),
) -> Target:
    return MockTarget(
        {
            "publish_targets": [str(t.address) for t in publish_targets],
            "sources": [],
        },
        address or Address("", target_name="tests"),
    )


def make_publish_target(address: Optional[Address] = None) -> Target:
    return MockPublishTarget({}, address or Address("", target_name="a_publish_target"))


def make_built_package():
    return BuiltPackage(
        digest="a_digest",
        artifacts=(),
    )


def run_publish_rule(
    rule_runner: RuleRunner,
    *,
    publish_request_types: List[Type[PublishRequest]],
    package_fieldset_types: List[Type[PackageFieldSet]],
    targets: List[Target],
    built_packages: List[BuiltPackage] = (),
):
    def UAI(unparsed_addresses: UnparsedAddressInputs):
        return [t for t in targets if t.address.spec in unparsed_addresses.values]

    with mock_console(rule_runner.options_bootstrapper) as (console, stdio_reader):
        union_membership = UnionMembership(
            {
                PublishRequest: publish_request_types,
                PackageFieldSet: package_fieldset_types,
            }
        )

        result: Publish = run_rule_with_mocks(
            publish,
            rule_args=[
                Targets(targets),
                union_membership,
            ],
            mock_gets=[
                MockGet(
                    output_type=Targets,
                    input_type=UnparsedAddressInputs,
                    mock=UAI,
                ),
                MockGet(
                    output_type=BuiltPackage,
                    input_type=PackageFieldSet,
                    mock=lambda _: built_packages.pop(0),
                ),
                MockGet(
                    output_type=PublishedPackage,
                    input_type=PublishRequest,
                    mock=lambda request: PublishedPackage(request.built_package, Address("//")),
                ),
            ],
            union_membership=union_membership,
        )
        assert not stdio_reader.get_stdout()
        return result.exit_code, stdio_reader.get_stderr()


def test_empty_targets_noops(rule_runner: RuleRunner) -> None:
    exit_code, stderr = run_publish_rule(
        rule_runner,
        publish_request_types=[MockPublishRequest],
        package_fieldset_types=[],
        targets=[],
    )
    assert exit_code == 0


def test_unpackagable_errors(rule_runner: RuleRunner) -> None:
    exit_code, stderr = run_publish_rule(
        rule_runner,
        publish_request_types=[MockPublishRequest],
        package_fieldset_types=[],
        targets=[make_target()],
    )

    assert exit_code == 1
    assert "is not a packageable target" in stderr


def test_packageable_no_targets_no_targets_no_targets(rule_runner: RuleRunner) -> None:
    exit_code, stderr = run_publish_rule(
        rule_runner,
        publish_request_types=[MockPublishRequest],
        package_fieldset_types=[MockTargetPackageFieldSet],
        targets=[make_target()],
        built_packages=[make_built_package()],
    )
    assert exit_code == 0
    assert stderr == ""


def test_packageable_with_target(rule_runner):
    publish_target = make_publish_target()
    publishee = make_target(publish_targets=[publish_target])

    exit_code, stderr = run_publish_rule(
        rule_runner,
        publish_request_types=[MockPublishRequest],
        package_fieldset_types=[MockTargetPackageFieldSet],
        targets=[publish_target, publishee],
        built_packages=[make_built_package()],
    )

    assert exit_code == 0
    assert f"Publishing {publishee.address}" in stderr
