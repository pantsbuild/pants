# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os
from dataclasses import dataclass
from textwrap import dedent
from typing import Sequence

from pants.engine.fs import Digest
from pants.engine.process import BashBinary, BinaryPathRequest, BinaryPaths, Process, ProcessResult
from pants.engine.rules import Get, MultiGet, collect_rules, rule


@dataclass(frozen=True)
class LocalToolsRequest:
    requests: tuple[BinaryPathRequest, ...]
    rationale: str
    output_directory: str

    @classmethod
    def for_tools(
        cls, *tools: str, rationale: str, output_directory: str, search_path: Sequence[str]
    ) -> LocalToolsRequest:
        return cls(
            requests=tuple(
                BinaryPathRequest(binary_name=tool, search_path=search_path) for tool in tools
            ),
            rationale=rationale,
            output_directory=output_directory,
        )


@dataclass(frozen=True)
class LocalTools:
    bin_directory: str
    tools: Digest


def create_shim(bash: str, tool: str) -> str:
    return dedent(
        f"""\
        #!{bash}
        exec "{tool}" "$@"
        """
    )


@rule
async def isolate_local_tools(tools_request: LocalToolsRequest, bash: BashBinary) -> LocalTools:
    """Creates a temporary bin directory with symlinks to all requested tools."""
    _bootstrap_tools = ("chmod", "mkdir", "printf")
    script_tools_requests = [
        BinaryPathRequest(
            binary_name=tool,
            search_path=("/usr/bin", "/bin", "/usr/local/bin"),
        )
        for tool in _bootstrap_tools
    ]
    all_requests = (*script_tools_requests, *tools_request.requests)
    all_binary_paths = await MultiGet(
        Get(BinaryPaths, BinaryPathRequest, request) for request in all_requests
    )
    binary_paths = [
        binary_paths.first_path_or_raise(request, rationale=tools_request.rationale).path
        for binary_paths, request in zip(all_binary_paths, all_requests)
    ]
    chmod, mkdir, printf = binary_paths[: len(_bootstrap_tools)]
    bin_relpath = tools_request.output_directory
    script = ";".join(
        (
            f"{mkdir} -p {bin_relpath}",
            *(
                " && ".join(
                    [
                        f"{printf} '{create_shim(bash.path, tool)}' > '{bin_relpath}/{os.path.basename(tool)}'",
                        f"{chmod} +x '{bin_relpath}/{os.path.basename(tool)}'",
                    ]
                )
                for tool in binary_paths[len(_bootstrap_tools) :]
            ),
        )
    )
    result = await Get(
        ProcessResult,
        Process(
            argv=(bash.path, "-c", script),
            description=f"Setup tool sandbox so that Pants can {tools_request.rationale}.",
            output_directories=(bin_relpath,),
        ),
    )
    return LocalTools(bin_relpath, result.output_digest)


def rules():
    return collect_rules()
