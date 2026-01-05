# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from _pytest.monkeypatch import MonkeyPatch

from pants.base.build_root import BuildRoot
from pants.core.environments.target_types import EnvironmentField
from pants.core.goals.export import (
    Export,
    ExportRequest,
    ExportResult,
    ExportResults,
    ExportSubsystem,
    PostProcessingCommand,
    export_goal,
    warn_exported_bin_conflicts,
)
from pants.core.util_rules.distdir import DistDir
from pants.engine.addresses import Address
from pants.engine.env_vars import EnvironmentVars, EnvironmentVarsRequest
from pants.engine.fs import CreateDigest, Digest, FileContent, Workspace
from pants.engine.process import InteractiveProcess, InteractiveProcessResult
from pants.engine.rules import QueryRule
from pants.engine.target import Target, Targets
from pants.engine.unions import UnionMembership, UnionRule
from pants.testutil.option_util import create_subsystem
from pants.testutil.rule_runner import RuleRunner, mock_console, run_rule_with_mocks


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
    """This is still necessary for writing files, which uses a `cp` process."""
    subprocess.check_call(
        ip.process.argv,
        stderr=subprocess.STDOUT,
        env={
            "PATH": os.environ.get("PATH", ""),
            "DIGEST_ROOT": os.path.join(rule_runner.build_root, "dist", "export", "mock"),
        },
    )
    return InteractiveProcessResult(0)


def list_files_with_paths(directory):
    file_paths = []
    for root, dirs, files in os.walk(directory):
        for file in files:
            full_path = os.path.join(root, file)
            file_paths.append(full_path)
    return file_paths


def run_export_rule(
    rule_runner: RuleRunner,
    monkeypatch: MonkeyPatch,
    resolves: list[str] | None = None,
    binaries: list[str] | None = None,
) -> tuple[int, str]:
    resolves = resolves or []
    binaries = binaries or []
    has_post_processing_commands = bool(resolves)
    union_membership = UnionMembership.from_rules([UnionRule(ExportRequest, MockExportRequest)])
    with open(os.path.join(rule_runner.build_root, "somefile"), "wb") as fp:
        fp.write(b"SOMEFILE")

    def noop():
        pass

    monkeypatch.setattr("pants.engine.intrinsics.task_side_effected", noop)
    with mock_console(rule_runner.options_bootstrapper) as (console, stdio_reader):

        def do_mock_export(__implicitly: tuple) -> ExportResults:
            req, typ = next(iter(__implicitly[0].items()))
            assert typ == ExportRequest

            if resolves:
                digest = rule_runner.request(
                    Digest, [CreateDigest([FileContent("foo/bar", b"BAR")])]
                )
                return ExportResults(
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
                )
            if binaries:
                digest = rule_runner.request(
                    Digest,
                    [
                        CreateDigest(
                            [FileContent(f"bins/{binary}/{binary}", b"BAR") for binary in binaries]
                        )
                    ],
                )
                return ExportResults(mock_export(digest, (), binary) for binary in binaries)
            raise Exception("No resolves or binaries specified")

        result: Export = run_rule_with_mocks(
            export_goal,
            rule_args=[
                console,
                Targets([]),
                Workspace(rule_runner.scheduler, _enforce_effects=False),
                union_membership,
                BuildRoot(),
                DistDir(relpath=Path("dist")),
                create_subsystem(ExportSubsystem, resolve=resolves, bin=binaries),
            ],
            # TODO: Create a rule_runner.call() method that invokes by-name, and use that to
            #  replace these rule_runner.request() by-type calls.
            mock_calls={
                "pants.engine.intrinsics.add_prefix": lambda *xs: rule_runner.request(Digest, xs),
                "pants.core.goals.export.export": do_mock_export,
                **(
                    {
                        "pants.engine.intrinsics._interactive_process": lambda ip: _mock_run(
                            rule_runner, ip
                        )
                    }
                    if has_post_processing_commands
                    else {}
                ),
                "pants.engine.intrinsics.merge_digests": lambda *iv: rule_runner.request(
                    Digest, iv
                ),
                "pants.core.util_rules.env_vars.environment_vars_subset": lambda *iv: rule_runner.request(
                    EnvironmentVars, iv
                ),
                "pants.engine.intrinsics.create_digest": lambda *iv: rule_runner.request(
                    Digest, iv
                ),
            },
            union_membership=union_membership,
        )
        return result.exit_code, stdio_reader.get_stdout()


def test_run_export_rule_resolve(monkeypatch) -> None:
    rule_runner = RuleRunner(
        rules=[
            UnionRule(ExportRequest, MockExportRequest),
            QueryRule(Digest, [CreateDigest]),
            QueryRule(EnvironmentVars, [EnvironmentVarsRequest]),
            QueryRule(InteractiveProcessResult, [InteractiveProcess]),
        ],
        target_types=[MockTarget],
    )
    exit_code, stdout = run_export_rule(rule_runner, monkeypatch, resolves=["resolve"])
    assert exit_code == 0
    assert "Wrote mock export for resolve to dist/export/mock" in stdout
    for filename in ["bar", "bar1", "bar2"]:
        expected_dist_path = os.path.join(
            rule_runner.build_root, "dist", "export", "mock", "foo", filename
        )
        assert os.path.isfile(expected_dist_path)
        with open(expected_dist_path, "rb") as fp:
            assert fp.read() == b"BAR"


def test_run_export_rule_binary(monkeypatch) -> None:
    rule_runner = RuleRunner(
        rules=[
            UnionRule(ExportRequest, MockExportRequest),
            QueryRule(Digest, [CreateDigest]),
            QueryRule(EnvironmentVars, [EnvironmentVarsRequest]),
            QueryRule(InteractiveProcessResult, [InteractiveProcess]),
        ],
        target_types=[MockTarget],
    )
    exit_code, stdout = run_export_rule(rule_runner, monkeypatch, binaries=["mybin"])
    assert exit_code == 0
    assert "Wrote mock export for mybin to dist/export/mock" in stdout
    for filename in ["mybin"]:
        expected_dist_path = os.path.join(
            rule_runner.build_root, "dist", "export", "mock", "bins", filename, filename
        )

        assert os.path.isfile(expected_dist_path)
        with open(expected_dist_path, "rb") as fp:
            assert fp.read() == b"BAR"


def test_warn_exported_bin_conflict() -> None:
    found_warnings = warn_exported_bin_conflicts(
        {
            "bin0": ["r0"],
            "bin1": ["r1"],
            "bin2": ["r0", "r1", "r2"],
        }
    )

    assert len(found_warnings) == 1, "did not detect the right number of conflicts"

    found_warning = found_warnings[0]
    assert "r0 was exported" in found_warning, "did not export from the correct resolve"
    assert "r1, r2" in found_warning, "did not report the other resolves correctly"
