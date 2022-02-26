# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os
from pathlib import Path
from typing import List, Tuple

from pants.base.build_root import BuildRoot
from pants.core.goals.export import (
    Export,
    ExportRequest,
    ExportResult,
    ExportResults,
    Symlink,
    export,
)
from pants.core.util_rules.distdir import DistDir
from pants.engine.addresses import Address
from pants.engine.fs import AddPrefix, CreateDigest, Digest, FileContent, MergeDigests, Workspace
from pants.engine.rules import QueryRule
from pants.engine.target import Target, Targets
from pants.engine.unions import UnionMembership, UnionRule
from pants.testutil.option_util import create_options_bootstrapper
from pants.testutil.rule_runner import MockGet, RuleRunner, mock_console, run_rule_with_mocks


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
    symlinks: tuple[Symlink, ...],
    post_processing_shell_cmds: tuple[str, ...],
) -> ExportResult:
    return ExportResult(
        description=f"mock export for {','.join(t.address.spec for t in edr.targets)}",
        reldir="mock",
        digest=digest,
        symlinks=symlinks,
        post_processing_shell_cmds=post_processing_shell_cmds,
    )


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
                    input_type=ExportRequest,
                    mock=lambda req: ExportResults(
                        (
                            mock_export(
                                req,
                                digest,
                                (Symlink("somefile", "link_to_somefile"),),
                                (
                                    'cp "${DIGEST_ROOT}/foo/bar" "${DIGEST_ROOT}/foo/bar_copy1"',
                                    'cp "${DIGEST_ROOT}/foo/bar" "${DIGEST_ROOT}/foo/bar_copy2"',
                                ),
                            ),
                        )
                    ),
                ),
                MockGet(
                    output_type=Digest,
                    input_type=MergeDigests,
                    mock=lambda md: rule_runner.request(Digest, [md]),
                ),
                MockGet(
                    output_type=Digest,
                    input_type=AddPrefix,
                    mock=lambda ap: rule_runner.request(Digest, [ap]),
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
        ],
        target_types=[MockTarget],
    )
    exit_code, stdout = run_export_rule(rule_runner, [make_target("foo/bar", "baz")])
    assert exit_code == 0
    assert "Wrote mock export for foo/bar:baz to dist/export/mock" in stdout
    for filename in ["bar", "bar_copy1", "bar_copy2"]:
        expected_dist_path = os.path.join(
            rule_runner.build_root, "dist", "export", "mock", "foo", filename
        )
        assert os.path.isfile(expected_dist_path)
        with open(expected_dist_path, "rb") as fp:
            assert fp.read() == b"BAR"

    symlink = "dist/export/mock/link_to_somefile"
    assert os.path.islink(symlink)
    assert os.readlink(symlink) == os.path.join(rule_runner.build_root, "somefile")
    with open(symlink, "rb") as fp:
        assert fp.read() == b"SOMEFILE"
