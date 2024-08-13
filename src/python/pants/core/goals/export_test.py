# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import List, Tuple

from _pytest.monkeypatch import MonkeyPatch

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
from pants.core.util_rules.environments import EnvironmentField
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
    digest: Digest,
    post_processing_cmds: tuple[PostProcessingCommand, ...],
    resolve: str,
) -> ExportResult:
    return ExportResult(
        description=f"mock export for {resolve}",
        reldir="mock",
        digest=digest,
        post_processing_cmds=post_processing_cmds,
        resolve=resolve,
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


def run_export_rule(
    rule_runner: RuleRunner, monkeypatch: MonkeyPatch, resolves: List[str]
) -> Tuple[int, str]:
    union_membership = UnionMembership({ExportRequest: [MockExportRequest]})
    with open(os.path.join(rule_runner.build_root, "somefile"), "wb") as fp:
        fp.write(b"SOMEFILE")

    def noop():
        pass

    monkeypatch.setattr("pants.engine.intrinsics.task_side_effected", noop)
    with mock_console(rule_runner.options_bootstrapper) as (console, stdio_reader):
        digest = rule_runner.request(Digest, [CreateDigest([FileContent("foo/bar", b"BAR")])])
        result: Export = run_rule_with_mocks(
            export,
            rule_args=[
                console,
                Targets([]),
                Workspace(rule_runner.scheduler, _enforce_effects=False),
                union_membership,
                BuildRoot(),
                DistDir(relpath=Path("dist")),
                create_subsystem(ExportSubsystem, resolve=resolves),
            ],
            mock_gets=[
                MockGet(
                    output_type=ExportResults,
                    input_types=(ExportRequest,),
                    mock=lambda req: ExportResults(
                        (
                            mock_export(
                                digest,
                                (
                                    PostProcessingCommand(
                                        ["cp", "{digest_root}/foo/bar", "{digest_root}/foo/bar1"]
                                    ),
                                    PostProcessingCommand(
                                        ["cp", "{digest_root}/foo/bar", "{digest_root}/foo/bar2"]
                                    ),
                                ),
                                resolves[0],
                            ),
                        )
                    ),
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


def test_run_export_rule(monkeypatch) -> None:
    rule_runner = RuleRunner(
        rules=[
            UnionRule(ExportRequest, MockExportRequest),
            QueryRule(Digest, [CreateDigest]),
            QueryRule(EnvironmentVars, [EnvironmentVarsRequest]),
            QueryRule(InteractiveProcessResult, [InteractiveProcess]),
        ],
        target_types=[MockTarget],
    )

    exit_code, stdout = run_export_rule(rule_runner, monkeypatch, ["resolve"])
    assert exit_code == 0
    assert "Wrote mock export for resolve to dist/export/mock" in stdout
    for filename in ["bar", "bar1", "bar2"]:
        expected_dist_path = os.path.join(
            rule_runner.build_root, "dist", "export", "mock", "foo", filename
        )
        assert os.path.isfile(expected_dist_path)
        with open(expected_dist_path, "rb") as fp:
            assert fp.read() == b"BAR"


def _e(path, env):
    return make_target(path, path, env)
