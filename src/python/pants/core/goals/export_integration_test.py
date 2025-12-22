# Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import os.path
from abc import ABC, abstractmethod
from dataclasses import dataclass

import pytest

from pants.core.goals import export
from pants.core.goals.export import (
    Export,
    ExportedBinary,
    ExportRequest,
    ExportResult,
    ExportResults,
    ExportSubsystem,
)
from pants.core.util_rules import archive, distdir
from pants.engine.engine_aware import EngineAwareParameter
from pants.engine.fs import CreateDigest, FileContent
from pants.engine.intrinsics import create_digest
from pants.engine.rules import concurrently, rule
from pants.engine.unions import UnionRule
from pants.testutil.rule_runner import RuleRunner, mock_console


class MyExportableBin(ABC):
    """ABC for all these exportable bins."""

    @classmethod
    @abstractmethod
    def bins_to_export(cls) -> tuple[ExportedBinary, ...]:
        pass


class MyBin0(MyExportableBin):
    @classmethod
    def bins_to_export(cls) -> tuple[ExportedBinary, ...]:
        return (ExportedBinary(name="mybin_0", path_in_export=f"{cls.__name__}.exe"),)


class MyBin1(MyExportableBin):
    @classmethod
    def bins_to_export(cls) -> tuple[ExportedBinary, ...]:
        return (ExportedBinary(name="mybin_1", path_in_export=f"{cls.__name__}.exe"),)


class MyBinMulti(MyExportableBin):
    """A test item exporting multiple binaries."""

    @classmethod
    def bins_to_export(cls) -> tuple[ExportedBinary, ...]:
        return (
            ExportedBinary(name="mybin_m0", path_in_export=f"{cls.__name__}_m0.exe"),
            ExportedBinary(name="mybin_m1", path_in_export=f"{cls.__name__}_m1.exe"),
        )


class MyBinConflict(MyExportableBin):
    """A test item with a binary conflict with MyBin0."""

    @classmethod
    def bins_to_export(cls) -> tuple[ExportedBinary, ...]:
        return (ExportedBinary(name="mybin_0", path_in_export=f"{cls.__name__}.exe"),)


classes = {e.__name__: e for e in [MyBin0, MyBin1, MyBinMulti, MyBinConflict]}


@dataclass(frozen=True)
class ExportMyBinRequest(ExportRequest):
    pass


@dataclass(frozen=True)
class _ExportMyBinForResolve(EngineAwareParameter):
    resolve: str


@rule
async def export_mybin(req: _ExportMyBinForResolve) -> ExportResult:
    """Sample export function.

    We don't use `UnionMembership` to find the class instance and create it with
    `_construct_subsystem` since that's not necessary for what we're testing.
    """
    tool = classes[req.resolve]
    bins_to_export = tool.bins_to_export()

    digest = await create_digest(
        CreateDigest(
            [
                *[FileContent(e.path_in_export, req.resolve.encode()) for e in bins_to_export],
                FileContent("readme.md", b"another file that would conflict if exported to `bin`"),
            ]
        ),
    )

    return ExportResult(
        description=f"Export for test item {req.resolve}",
        reldir=os.path.join("testitems", req.resolve),
        digest=digest,
        resolve=req.resolve,
        exported_binaries=bins_to_export,
    )


@rule
async def export_external_tools(
    request: ExportMyBinRequest, export: ExportSubsystem
) -> ExportResults:
    maybe_tools = await concurrently(
        export_mybin(_ExportMyBinForResolve(resolve)) for resolve in export.binaries
    )
    return ExportResults(maybe_tools)


@pytest.fixture
def rule_runner():
    return RuleRunner(
        rules=[
            *export.rules(),
            *archive.rules(),
            *distdir.rules(),
            export_mybin,
            export_external_tools,
            UnionRule(ExportRequest, ExportMyBinRequest),
        ],
    )


def assert_export(rule_runner: RuleRunner, cls, was_linked: bool = True) -> None:
    resolve = cls.__name__
    bins = cls.bins_to_export()

    for bin in bins:
        assert rule_runner.read_file(
            os.path.join("dist", "export", "testitems", resolve, bin.path_in_export)
        )
        linked_path = os.path.join("dist", "export", "bin", bin.name)
        linked_content = rule_runner.read_file(linked_path)
        if was_linked:
            assert linked_content == resolve, (
                f"bin {bin.name} was not linked to the `bin` directory, instead {linked_content!r} was"
            )
        else:
            assert linked_content != resolve, (
                f"bin {bin.name} was linked to `bin` directory but we expected it to not be"
            )


def test_export_binary(rule_runner):
    """Test we export binaries."""

    with mock_console(rule_runner.options_bootstrapper):
        result = rule_runner.run_goal_rule(Export, args=["--bin=MyBin0", "--bin=MyBin1"])
        assert result.exit_code == 0
    assert_export(rule_runner, MyBin0)
    assert_export(rule_runner, MyBin1)


def test_export_multiple_binaries(rule_runner):
    """Test that a single class can export multiple binaries."""
    with mock_console(rule_runner.options_bootstrapper):
        result = rule_runner.run_goal_rule(Export, args=["--bin=MyBinMulti"])
        assert result.exit_code == 0
    assert_export(rule_runner, MyBinMulti)


def test_export_conflict(rule_runner):
    """Test that we still export even with binary conflicts."""
    with mock_console(rule_runner.options_bootstrapper):
        result = rule_runner.run_goal_rule(Export, args=["--bin=MyBin0", "--bin=MyBinConflict"])
        assert result.exit_code == 0
    assert_export(rule_runner, MyBin0)
    assert_export(rule_runner, MyBinConflict, was_linked=False)
