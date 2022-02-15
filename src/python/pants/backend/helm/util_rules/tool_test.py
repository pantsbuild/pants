# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import pytest

from pants.backend.helm.subsystem import HelmSubsystem
from pants.backend.helm.target_types import HelmArtifactTarget
from pants.backend.helm.util_rules import tool
from pants.backend.helm.util_rules.tool import HelmBinary
from pants.core.util_rules import config_files, external_tool
from pants.engine import process
from pants.engine.fs import AddPrefix, Digest
from pants.engine.rules import QueryRule, SubsystemRule
from pants.testutil.rule_runner import RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        target_types=[HelmArtifactTarget],
        rules=[
            *config_files.rules(),
            *external_tool.rules(),
            *tool.rules(),
            *process.rules(),
            SubsystemRule(HelmSubsystem),
            QueryRule(HelmBinary, ()),
            QueryRule(Digest, (AddPrefix,)),
        ],
    )


def test_update_index_for_classic_repos(rule_runner: RuleRunner) -> None:
    repositories_opts = """{"jetstack": {"address": "https://charts.jetstack.io"}, "docker": {"address": "oci://docker.io"}}"""
    rule_runner.set_options([f"--helm-registries={repositories_opts}"])

    helm = rule_runner.request(HelmBinary, [])
    assert helm
    assert "@jetstack" in helm.repositories
    assert len(helm.repositories) == 1
