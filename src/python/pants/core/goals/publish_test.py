# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from typing import Iterable, List, Optional, Type

import pytest

from pants.build_graph.address import Address
from pants.core.goals.package import BuiltPackage, PackageFieldSet
from pants.core.goals.publish import (
    Publish,
    PublishProcess,
    PublishRequest,
    PublishTarget,
    PublishTargetField,
    publish,
)
from pants.engine.addresses import UnparsedAddressInputs
from pants.engine.process import InteractiveProcess, InteractiveProcessResult
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
    publish_process: Optional[InteractiveProcess] = InteractiveProcess(argv=[]),
    publish_exit_code: int = 0,
    publish_message: Optional[str] = None,
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
                console,
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
                    output_type=PublishProcess,
                    input_type=PublishRequest,
                    mock=lambda request: PublishProcess(
                        process=publish_process,
                        message=publish_message,
                    ),
                ),
                MockGet(
                    output_type=InteractiveProcessResult,
                    input_type=InteractiveProcess,
                    mock=lambda process: InteractiveProcessResult(exit_code=publish_exit_code),
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
    assert f"Published {publishee.address} to {publish_target.address}" in stderr


def test_none_publish_process(rule_runner):
    """When PublishProcess.process is None."""
    publish_target = make_publish_target()
    publishee = make_target(publish_targets=[publish_target])

    message_sentinel = "SENTINEL"

    exit_code, stderr = run_publish_rule(
        rule_runner,
        publish_request_types=[MockPublishRequest],
        package_fieldset_types=[MockTargetPackageFieldSet],
        targets=[publish_target, publishee],
        built_packages=[make_built_package()],
        publish_process=None,
        publish_message=message_sentinel,
    )

    assert exit_code == 0
    assert f"Unable to publish {publishee.address} to {publish_target.address}" in stderr
    assert message_sentinel in stderr


def test_packageable_with_target_failure(rule_runner):
    publish_target = make_publish_target()
    publishee = make_target(publish_targets=[publish_target])

    exit_code, stderr = run_publish_rule(
        rule_runner,
        publish_request_types=[MockPublishRequest],
        package_fieldset_types=[MockTargetPackageFieldSet],
        targets=[publish_target, publishee],
        built_packages=[make_built_package()],
        publish_exit_code=1,
    )

    assert exit_code == 1
    assert f"Failed to publish {publishee.address} to {publish_target.address}" in stderr
