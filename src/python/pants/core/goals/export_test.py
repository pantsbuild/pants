# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Iterable, List, Tuple

import pytest

from pants.base.build_root import BuildRoot
from pants.core.goals.export import (
    Export,
    ExportRequest,
    ExportResult,
    ExportResults,
    ExportSubsystem,
    PostProcessingCommand,
    export,
)
from pants.core.goals.generate_lockfiles import KnownUserResolveNames, KnownUserResolveNamesRequest
from pants.core.util_rules.distdir import DistDir
from pants.core.util_rules.environments import (
    EnvironmentField,
    EnvironmentNameRequest,
    EnvironmentTarget,
    LocalEnvironmentTarget,
    RemoteEnvironmentTarget,
)
from pants.engine.addresses import Address
from pants.engine.env_vars import EnvironmentVars, EnvironmentVarsRequest
from pants.engine.fs import AddPrefix, CreateDigest, Digest, FileContent, MergeDigests, Workspace
from pants.engine.process import InteractiveProcess, InteractiveProcessResult
from pants.engine.rules import QueryRule
from pants.engine.target import Target, Targets
from pants.engine.unions import UnionMembership, UnionRule
from pants.testutil.option_util import create_subsystem
from pants.testutil.rule_runner import (
    MockEffect,
    MockGet,
    RuleRunner,
    mock_console,
    run_rule_with_mocks,
)


class MockTarget(Target):
    alias = "target"
    core_fields = (EnvironmentField,)


def make_target(path: str, target_name: str, environment_name: str | None = None) -> Target:
    return MockTarget(
        {EnvironmentField.alias: environment_name}, Address(path, target_name=target_name)
    )


class MockExportRequest(ExportRequest):
    pass


def mock_export(
    edr: ExportRequest,
    digest: Digest,
    post_processing_cmds: tuple[PostProcessingCommand, ...],
) -> ExportResult:
    return ExportResult(
        description=f"mock export for {','.join(t.address.spec for t in edr.targets)}",
        reldir="mock",
        digest=digest,
        post_processing_cmds=post_processing_cmds,
    )


def _mock_run(rule_runner: RuleRunner, ip: InteractiveProcess) -> InteractiveProcessResult:
    subprocess.check_call(
        ip.process.argv,
        stderr=subprocess.STDOUT,
        env={
            "PATH": os.environ.get("PATH", ""),
            "DIGEST_ROOT": os.path.join(rule_runner.build_root, "dist", "export", "mock"),
        },
    )
    return InteractiveProcessResult(0)


def run_export_rule(rule_runner: RuleRunner, targets: List[Target]) -> Tuple[int, str]:
    union_membership = UnionMembership({ExportRequest: [MockExportRequest]})
    with open(os.path.join(rule_runner.build_root, "somefile"), "wb") as fp:
        fp.write(b"SOMEFILE")
    with mock_console(rule_runner.options_bootstrapper) as (console, stdio_reader):
        digest = rule_runner.request(Digest, [CreateDigest([FileContent("foo/bar", b"BAR")])])
        result: Export = run_rule_with_mocks(
            export,
            rule_args=[
                console,
                Targets(targets),
                Workspace(rule_runner.scheduler, _enforce_effects=False),
                union_membership,
                BuildRoot(),
                DistDir(relpath=Path("dist")),
                create_subsystem(ExportSubsystem, resolve=[]),
            ],
            mock_gets=[
                MockGet(
                    output_type=ExportResults,
                    input_types=(ExportRequest,),
                    mock=lambda req: ExportResults(
                        (
                            mock_export(
                                req,
                                digest,
                                (
                                    PostProcessingCommand(
                                        ["cp", "{digest_root}/foo/bar", "{digest_root}/foo/bar1"]
                                    ),
                                    PostProcessingCommand(
                                        ["cp", "{digest_root}/foo/bar", "{digest_root}/foo/bar2"]
                                    ),
                                ),
                            ),
                        )
                    ),
                ),
                MockGet(
                    output_type=EnvironmentTarget,
                    input_types=(EnvironmentNameRequest,),
                    mock=lambda req: EnvironmentTarget(req.raw_value, None),
                ),
                rule_runner.do_not_use_mock(Digest, (MergeDigests,)),
                rule_runner.do_not_use_mock(Digest, (AddPrefix,)),
                rule_runner.do_not_use_mock(EnvironmentVars, (EnvironmentVarsRequest,)),
                rule_runner.do_not_use_mock(KnownUserResolveNames, (KnownUserResolveNamesRequest,)),
                MockEffect(
                    output_type=InteractiveProcessResult,
                    input_types=(InteractiveProcess,),
                    mock=lambda ip: _mock_run(rule_runner, ip),
                ),
            ],
            union_membership=union_membership,
        )
        return result.exit_code, stdio_reader.get_stdout()


def test_run_export_rule() -> None:
    rule_runner = RuleRunner(
        rules=[
            UnionRule(ExportRequest, MockExportRequest),
            QueryRule(Digest, [CreateDigest]),
            QueryRule(EnvironmentVars, [EnvironmentVarsRequest]),
            QueryRule(InteractiveProcessResult, [InteractiveProcess]),
        ],
        target_types=[MockTarget],
    )
    exit_code, stdout = run_export_rule(rule_runner, [make_target("foo/bar", "baz")])
    assert exit_code == 0
    assert "Wrote mock export for foo/bar:baz to dist/export/mock" in stdout
    for filename in ["bar", "bar1", "bar2"]:
        expected_dist_path = os.path.join(
            rule_runner.build_root, "dist", "export", "mock", "foo", filename
        )
        assert os.path.isfile(expected_dist_path)
        with open(expected_dist_path, "rb") as fp:
            assert fp.read() == b"BAR"


def _e(path, env):
    return make_target(path, path, env)


@pytest.mark.parametrize(
    ["targets", "err_present", "err_absent"],
    [
        # Only a local environment
        [[_e("a", "l")], [], ["`a:a`"]],
        # The remote environment should warn, the local environment should not
        [[_e("a", "l"), _e("b", "r")], ["target `b:b`"], ["`a:a`"]],
        # Only a remote environment, which should warn
        [[_e("b", "r")], ["target `b:b`, which specifies", "environment `r`"], []],
        # Two targets with the same remote environment (should trigger short plural message)
        [
            [_e("b", "r"), _e("c", "r")],
            ["targets `b:b`, `c:c`, which specify", "environment `r`"],
            [],
        ],
        # Two targets, each with their own remote environment, each should warn separately
        [
            [_e("b", "r"), _e("c", "r2")],
            [
                "target `b:b`, which specifies",
                "target `c:c`, which specifies",
                "environment `r`",
                "environment `r2`",
            ],
            ["`b:b`, `c:c`"],
        ],
        # Four targets with the same remote environment (should trigger long plural message, omitting the later targets by lex order)
        [
            [_e("b", "r"), _e("c", "r"), _e("d", "r"), _e("e", "r")],
            [
                "targets including `b:b`, `c:c`, `d:d` (and others), which specify",
                "environment `r`",
            ],
            ["`e:e`"],
        ],
    ],
)
def test_warnings_for_non_local_target_environments(
    targets: Iterable[Target], err_present: Iterable[str], err_absent: Iterable[str]
) -> None:
    rule_runner = RuleRunner(
        rules=[
            UnionRule(ExportRequest, MockExportRequest),
            QueryRule(Digest, [CreateDigest]),
            QueryRule(EnvironmentVars, [EnvironmentVarsRequest]),
            QueryRule(InteractiveProcessResult, [InteractiveProcess]),
        ],
        target_types=[MockTarget, LocalEnvironmentTarget, RemoteEnvironmentTarget],
    )

    union_membership = UnionMembership({ExportRequest: [MockExportRequest]})
    with open(os.path.join(rule_runner.build_root, "somefile"), "wb") as fp:
        fp.write(b"SOMEFILE")
    with mock_console(rule_runner.options_bootstrapper) as (console, stdio_reader):
        digest = rule_runner.request(Digest, [CreateDigest([FileContent("foo/bar", b"BAR")])])
        run_rule_with_mocks(
            export,
            rule_args=[
                console,
                Targets(targets),
                Workspace(rule_runner.scheduler, _enforce_effects=False),
                union_membership,
                BuildRoot(),
                DistDir(relpath=Path("dist")),
                create_subsystem(ExportSubsystem, resolve=[]),
            ],
            mock_gets=[
                MockGet(
                    output_type=ExportResults,
                    input_types=(ExportRequest,),
                    mock=lambda req: ExportResults(
                        (
                            mock_export(
                                req,
                                digest,
                                (),
                            ),
                        )
                    ),
                ),
                rule_runner.do_not_use_mock(Digest, (MergeDigests,)),
                MockGet(
                    output_type=EnvironmentTarget,
                    input_types=(EnvironmentNameRequest,),
                    mock=_give_an_environment,
                ),
                rule_runner.do_not_use_mock(Digest, (AddPrefix,)),
                rule_runner.do_not_use_mock(EnvironmentVars, (EnvironmentVarsRequest,)),
                rule_runner.do_not_use_mock(KnownUserResolveNames, (KnownUserResolveNamesRequest,)),
                MockEffect(
                    output_type=InteractiveProcessResult,
                    input_types=(InteractiveProcess,),
                    mock=lambda ip: _mock_run(rule_runner, ip),
                ),
            ],
            union_membership=union_membership,
        )

        # Messages
        stderr = stdio_reader.get_stderr()
        for present in err_present:
            assert present in stderr
        for absent in err_absent:
            assert absent not in stderr


def _give_an_environment(enr: EnvironmentNameRequest) -> EnvironmentTarget:
    if enr.raw_value.startswith("l"):
        return EnvironmentTarget(
            enr.raw_value, LocalEnvironmentTarget({}, Address("local", target_name="local"))
        )
    elif enr.raw_value.startswith("r"):
        return EnvironmentTarget(
            enr.raw_value, RemoteEnvironmentTarget({}, Address("remote", target_name="remote"))
        )
    else:
        raise Exception()
