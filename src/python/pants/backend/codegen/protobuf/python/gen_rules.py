# coding=utf-8
# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (
    absolute_import,
    division,
    generators,
    nested_scopes,
    print_function,
    unicode_literals,
    with_statement,
)

import os

from pants.backend.codegen.protobuf.subsystems.protoc import Protoc
from pants.base.build_root import BuildRoot
from pants.core.util_rules.distdir import DistDir
from pants.core.util_rules.external_tool import DownloadedExternalTool, ExternalToolRequest
from pants.engine.console import Console
from pants.engine.fs import DirectoryToMaterialize, Workspace
from pants.engine.goal import Goal, GoalSubsystem, LineOriented
from pants.engine.platform import Platform
from pants.engine.rules import goal_rule, subsystem_rule
from pants.engine.selectors import Get


class DummyGetProtocOptions(LineOriented, GoalSubsystem):
    """Create a runnable binary."""

    name = "dummy-get-protoc"


class DummyGetProtoc(Goal):
    subsystem_cls = DummyGetProtocOptions


@goal_rule
async def dummy_copy_protoc_to_dist(
    console: Console,
    workspace: Workspace,
    options: DummyGetProtocOptions,
    distdir: DistDir,
    buildroot: BuildRoot,
    protoc: Protoc,
) -> DummyGetProtoc:
    """A dummy goal rule to demonstrate that downloading and extracting external tools works.

    This rule should be deleted once
    """
    downloaded_protoc_binary = await Get[DownloadedExternalTool](
        ExternalToolRequest, protoc.get_request(Platform.current)
    )
    result = workspace.materialize_directory(
        DirectoryToMaterialize(
            directory_digest=downloaded_protoc_binary.digest, path_prefix=str(distdir.relpath)
        )
    )
    with options.line_oriented(console) as print_stdout:
        for path in result.output_paths:
            print_stdout(f"Wrote {os.path.relpath(path, buildroot.path)}")
    return DummyGetProtoc(exit_code=0)


def rules():
    return [dummy_copy_protoc_to_dist, subsystem_rule(Protoc)]
