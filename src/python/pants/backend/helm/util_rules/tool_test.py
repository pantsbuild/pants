# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import re

import pytest

from pants.backend.helm.subsystems.helm import HelmSubsystem
from pants.backend.helm.subsystems.helm import rules as helm_subsytem_rules
from pants.backend.helm.util_rules import tool
from pants.backend.helm.util_rules.tool import HelmBinary, HelmProcess
from pants.core.util_rules import config_files, external_tool
from pants.engine import process
from pants.engine.internals.native_engine import EMPTY_DIGEST
from pants.engine.platform import Platform
from pants.engine.process import Process, ProcessCacheScope, ProcessResult
from pants.engine.rules import QueryRule
from pants.testutil.rule_runner import RuleRunner
from pants.util.frozendict import FrozenDict


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        target_types=[],
        rules=[
            *config_files.rules(),
            *external_tool.rules(),
            *tool.rules(),
            *process.rules(),
            *helm_subsytem_rules(),
            QueryRule(HelmBinary, ()),
            QueryRule(HelmSubsystem, ()),
            QueryRule(Process, (HelmProcess,)),
            QueryRule(ProcessResult, (HelmProcess,)),
        ],
    )


def test_initialises_basic_helm_binary(rule_runner: RuleRunner) -> None:
    helm_subsystem = rule_runner.request(HelmSubsystem, [])
    helm_binary = rule_runner.request(HelmBinary, [])
    assert helm_binary
    assert helm_binary.path == f"__helm/{helm_subsystem.generate_exe(Platform.current)}"


def test_initialise_classic_repos(rule_runner: RuleRunner) -> None:
    repositories_opts = """{"jetstack": {"address": "https://charts.jetstack.io"}}"""
    rule_runner.set_options([f"--helm-classic-repositories={repositories_opts}"])

    process = HelmProcess(
        argv=["repo", "list"],
        input_digest=EMPTY_DIGEST,
        description="List installed classic repositories",
    )
    result = rule_runner.request(ProcessResult, [process])

    # The result of the `helm repo list` command is a table with a header like
    #    NAME     URL
    #    alias    http://example.com/charts
    #
    # So to build the test expectation we parse that output keeping
    # the repository's alias and url to be used in the comparison
    table_rows = result.stdout.decode().splitlines()[1:]
    configured_repos = [
        (columns[0].strip(), columns[1].strip())
        for columns in (re.split(r"\t+", line.rstrip()) for line in table_rows)
    ]

    assert configured_repos == [("jetstack", "https://charts.jetstack.io")]


def test_create_helm_process(rule_runner: RuleRunner) -> None:
    helm_binary = rule_runner.request(HelmBinary, [])

    helm_argv = ["foo"]
    helm_process = HelmProcess(
        helm_argv,
        input_digest=EMPTY_DIGEST,
        description="Test Helm process",
        extra_immutable_input_digests={"foo_digest": EMPTY_DIGEST},
        extra_env={"FOO_ENV": "1"},
        output_directories=["foo_out"],
        cache_scope=ProcessCacheScope.ALWAYS,
    )
    process = rule_runner.request(Process, [helm_process])

    assert process.argv == (helm_binary.path, *helm_argv)
    assert process.description == helm_process.description
    assert process.level == helm_process.level
    assert process.input_digest == helm_process.input_digest
    assert process.immutable_input_digests == FrozenDict(
        {**helm_binary.immutable_input_digests, **helm_process.extra_immutable_input_digests}
    )
    assert process.env == FrozenDict({**helm_binary.env, **helm_process.extra_env})
    assert process.output_directories == helm_process.output_directories
    assert process.cache_scope == helm_process.cache_scope
