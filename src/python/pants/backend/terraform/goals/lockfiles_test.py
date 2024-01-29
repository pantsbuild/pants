# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import pytest

from pants.backend.terraform.testutil import (
    StandardDeployment,
    rule_runner_with_auto_approve,
    standard_deployment,
    terraform_lockfile,
    terraform_lockfile_regenerated,
)
from pants.core.goals.generate_lockfiles import GenerateLockfilesGoal
from pants.testutil.rule_runner import RuleRunner

rule_runner = rule_runner_with_auto_approve
standard_deployment = standard_deployment


@pytest.mark.parametrize("existing_lockfile", [False, True])
def test_integration_generate_lockfile(
    rule_runner: RuleRunner, standard_deployment: StandardDeployment, existing_lockfile: bool
) -> None:
    rule_runner.write_files(standard_deployment.files)
    if existing_lockfile:
        rule_runner.write_files({"src/tf/.terraform.lock.hcl": terraform_lockfile})

    result = rule_runner.run_goal_rule(
        GenerateLockfilesGoal,
        global_args=[*rule_runner.options_bootstrapper.args],
        args=["--generate-lockfiles-resolve=src/tf:mod"],
    )

    # assert Pants things we succeeded
    assert result.exit_code == 0

    # assert Terraform wrote the lockfile
    lockfile_contents = rule_runner.read_file("src/tf/.terraform.lock.hcl")
    assert lockfile_contents == terraform_lockfile_regenerated
