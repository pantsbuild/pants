# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import List, Tuple

from pants.base.build_root import BuildRoot
from pants.core.goals.export import (
    Export,
    ExportRequest,
    ExportResult,
    ExportResults,
    PostProcessingCommand,
    export,
)
from pants.core.util_rules.distdir import DistDir
from pants.core.util_rules.environments import EnvironmentNameRequest, EnvironmentTarget
from pants.engine.addresses import Address
from pants.engine.env_vars import EnvironmentVars, EnvironmentVarsRequest
from pants.engine.fs import AddPrefix, CreateDigest, Digest, FileContent, MergeDigests, Workspace
from pants.engine.process import InteractiveProcess, InteractiveProcessResult
from pants.engine.rules import QueryRule
from pants.engine.target import Target, Targets
from pants.engine.unions import UnionMembership, UnionRule
from pants.testutil.option_util import create_options_bootstrapper
from pants.testutil.rule_runner import (
    MockEffect,
    MockGet,
    RuleRunner,
    mock_console,
    run_rule_with_mocks,
)


class MockTarget(Target):
    alias = "target"
    core_fields = ()


def make_target(path: str, target_name: str) -> Target:
    return MockTarget({}, Address(path, target_name=target_name))


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
    with mock_console(create_options_bootstrapper()) as (console, stdio_reader):
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
                rule_runner.do_not_use_mock(Digest, (MergeDigests,)),
                rule_runner.do_not_use_mock(EnvironmentTarget, (EnvironmentNameRequest,)),
                rule_runner.do_not_use_mock(Digest, (AddPrefix,)),
                rule_runner.do_not_use_mock(EnvironmentVars, (EnvironmentVarsRequest,)),
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


def test_bloop() -> None:
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
