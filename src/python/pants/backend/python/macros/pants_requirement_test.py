# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import pytest

from pants.backend.python.macros import pants_requirement
from pants.backend.python.macros.pants_requirement import (
    GenerateFromPantsRequirementRequest,
    PantsDistField,
    PantsRequirementTargetGenerator,
)
from pants.backend.python.pip_requirement import PipRequirement
from pants.backend.python.target_types import (
    PythonRequirementModulesField,
    PythonRequirementsField,
    PythonRequirementTarget,
)
from pants.base.build_environment import pants_version
from pants.engine.addresses import Address
from pants.engine.target import GeneratedTargets, InvalidFieldException
from pants.testutil.rule_runner import QueryRule, RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=(
            *pants_requirement.rules(),
            QueryRule(GeneratedTargets, [GenerateFromPantsRequirementRequest]),
        ),
        target_types=[PantsRequirementTargetGenerator],
    )


def assert_pants_requirement(
    rule_runner: RuleRunner,
    build_file_entry: str,
    *,
    expected_dist: str = "pantsbuild.pants",
    expected_module: str = "pants",
) -> None:
    rule_runner.write_files({"BUILD": f"{build_file_entry}\n"})
    generator = rule_runner.get_target(Address("", target_name="pants_req"))
    result = rule_runner.request(GeneratedTargets, [GenerateFromPantsRequirementRequest(generator)])

    assert len(result) == 1
    generated = list(result.values())[0]
    assert isinstance(generated, PythonRequirementTarget)
    assert generated.address == generator.address.create_generated(expected_dist)

    assert generated[PythonRequirementsField].value == (
        PipRequirement.parse(f"{expected_dist}=={pants_version()}"),
    )
    modules = generated[PythonRequirementModulesField].value
    assert modules == (expected_module,)


def test_default(rule_runner: RuleRunner) -> None:
    assert_pants_requirement(rule_runner, "pants_requirement(name='pants_req')")


def test_override_dist(rule_runner: RuleRunner) -> None:
    assert_pants_requirement(
        rule_runner,
        "pants_requirement(name='pants_req', dist='pantsbuild.pants.contrib')",
        expected_dist="pantsbuild.pants.contrib",
        expected_module="pants.contrib",
    )


def test_override_modules(rule_runner: RuleRunner) -> None:
    assert_pants_requirement(
        rule_runner,
        "pants_requirement(name='pants_req', modules=['fake'])",
        expected_module="fake",
    )


def test_bad_dist(rule_runner: RuleRunner) -> None:
    with pytest.raises(InvalidFieldException):
        PantsDistField("not_pants.dist", Address("", target_name="t"))
