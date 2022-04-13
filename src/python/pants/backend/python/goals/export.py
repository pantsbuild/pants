# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
import os
from collections import defaultdict
from dataclasses import dataclass
from typing import DefaultDict, Iterable, cast

from pants.backend.python.subsystems.setup import PythonSetup
from pants.backend.python.target_types import PythonResolveField
from pants.backend.python.util_rules.interpreter_constraints import InterpreterConstraints
from pants.backend.python.util_rules.pex import Pex, PexProcess, PexRequest
from pants.backend.python.util_rules.pex_cli import PexPEX
from pants.backend.python.util_rules.pex_from_targets import RequirementsPexRequest
from pants.core.goals.export import (
    ExportError,
    ExportRequest,
    ExportResult,
    ExportResults,
    PostProcessingCommand,
)
from pants.core.util_rules.distdir import DistDir
from pants.engine.engine_aware import EngineAwareParameter
from pants.engine.internals.native_engine import AddPrefix, Digest, MergeDigests
from pants.engine.internals.selectors import Get, MultiGet
from pants.engine.process import ProcessResult
from pants.engine.rules import collect_rules, rule
from pants.engine.target import Target
from pants.engine.unions import UnionMembership, UnionRule, union
from pants.util.docutil import bin_name
from pants.util.strutil import path_safe

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ExportVenvsRequest(ExportRequest):
    pass


@dataclass(frozen=True)
class _ExportVenvRequest(EngineAwareParameter):
    resolve: str | None
    root_python_targets: tuple[Target, ...]

    def debug_hint(self) -> str | None:
        return self.resolve


@union
class ExportPythonToolSentinel:
    """Pythion tools use this as an entry point to say how to export their tool virtualenv."""


@dataclass(frozen=True)
class ExportPythonTool:
    resolve_name: str
    pex_request: PexRequest


@rule
async def export_virtualenv(
    request: _ExportVenvRequest, python_setup: PythonSetup, pex_pex: PexPEX
) -> ExportResult:
    if request.resolve:
        interpreter_constraints = InterpreterConstraints(
            python_setup.resolves_to_interpreter_constraints.get(
                request.resolve, python_setup.interpreter_constraints
            )
        )
    else:
        interpreter_constraints = InterpreterConstraints.create_from_targets(
            request.root_python_targets, python_setup
        ) or InterpreterConstraints(python_setup.interpreter_constraints)

    min_interpreter = interpreter_constraints.snap_to_minimum(python_setup.interpreter_universe)
    if not min_interpreter:
        err_msg = (
            (
                f"The resolve '{request.resolve}' (from `[python].resolves`) has invalid interpreter "
                f"constraints, which are set via `[python].resolves_to_interpreter_constraints`: "
                f"{interpreter_constraints}. Could not determine the minimum compatible interpreter."
            )
            if request.resolve
            else (
                "The following interpreter constraints were computed for all the targets for which "
                f"export was requested: {interpreter_constraints}. There is no python interpreter "
                "compatible with these constraints. Please restrict the target set to one that shares "
                "a compatible interpreter."
            )
        )
        raise ExportError(err_msg)

    requirements_pex = await Get(
        Pex,
        RequirementsPexRequest(
            (tgt.address for tgt in request.root_python_targets),
            hardcoded_interpreter_constraints=min_interpreter,
        ),
    )

    # Get the full python version (including patch #), so we can use it as the venv name.
    res = await Get(
        ProcessResult,
        PexProcess(
            pex=requirements_pex,
            description="Get interpreter version",
            argv=["-c", "import sys; print('.'.join(str(x) for x in sys.version_info[0:3]))"],
        ),
    )
    py_version = res.stdout.strip().decode()

    dest = (
        os.path.join("python", "virtualenvs", path_safe(request.resolve))
        if request.resolve
        else os.path.join("python", "virtualenv")
    )

    merged_digest = await Get(Digest, MergeDigests([pex_pex.digest, requirements_pex.digest]))
    pex_pex_path = os.path.join("{digest_root}", pex_pex.exe)
    return ExportResult(
        f"virtualenv for the resolve '{request.resolve}' (using {min_interpreter})",
        dest,
        digest=merged_digest,
        post_processing_cmds=[
            PostProcessingCommand(
                [
                    pex_pex_path,
                    os.path.join("{digest_root}", requirements_pex.name),
                    "venv",
                    "--pip",
                    "--collisions-ok",
                    "--remove=all",
                    f"{{digest_root}}/{py_version}",
                ],
                {"PEX_MODULE": "pex.tools"},
            ),
            PostProcessingCommand(["rm", "-f", pex_pex_path]),
        ],
    )


@rule
async def export_tool(request: ExportPythonTool, pex_pex: PexPEX) -> ExportResult:
    dest = os.path.join("python", "virtualenvs", "tools")
    pex = await Get(Pex, PexRequest, request.pex_request)

    # NOTE: We add a unique-per-tool prefix to the pex_pex path to avoid conflicts when
    # multiple tools are concurrently exporting. Without this prefix all the `export_tool`
    # invocations write the pex_pex to `python/virtualenvs/tools/pex`, and the `rm -f` of
    # the pex_pex path in one export will delete the binary out from under the others.
    pex_pex_dir = f".{request.resolve_name}.tmp"
    pex_pex_dest = os.path.join("{digest_root}", pex_pex_dir)
    pex_pex_digest = await Get(Digest, AddPrefix(pex_pex.digest, pex_pex_dir))

    merged_digest = await Get(Digest, MergeDigests([pex_pex_digest, pex.digest]))
    return ExportResult(
        f"virtualenv for the tool '{request.resolve_name}'",
        dest,
        digest=merged_digest,
        post_processing_cmds=[
            PostProcessingCommand(
                [
                    os.path.join(pex_pex_dest, pex_pex.exe),
                    os.path.join("{digest_root}", pex.name),
                    "venv",
                    "--collisions-ok",
                    "--remove=all",
                    f"{{digest_root}}/{request.resolve_name}",
                ],
                {"PEX_MODULE": "pex.tools"},
            ),
            PostProcessingCommand(["rm", "-rf", pex_pex_dest]),
        ],
    )


@rule
async def export_virtualenvs(
    request: ExportVenvsRequest,
    python_setup: PythonSetup,
    dist_dir: DistDir,
    union_membership: UnionMembership,
) -> ExportResults:
    resolve_to_root_targets: DefaultDict[str, list[Target]] = defaultdict(list)
    for tgt in request.targets:
        if not tgt.has_field(PythonResolveField):
            continue
        resolve = tgt[PythonResolveField].normalized_value(python_setup)
        resolve_to_root_targets[resolve].append(tgt)

    venvs = await MultiGet(
        Get(
            ExportResult,
            _ExportVenvRequest(resolve if python_setup.enable_resolves else None, tuple(tgts)),
        )
        for resolve, tgts in resolve_to_root_targets.items()
    )

    no_resolves_dest = dist_dir.relpath / "python" / "virtualenv"
    if venvs and python_setup.enable_resolves and no_resolves_dest.exists():
        logger.warning(
            f"Because `[python].enable_resolves` is true, `{bin_name()} export ::` no longer "
            f"writes virtualenvs to {no_resolves_dest}, but instead underneath "
            f"{dist_dir.relpath / 'python' / 'virtualenvs'}. You will need to "
            "update your IDE to point to the new virtualenv.\n\n"
            f"To silence this error, delete {no_resolves_dest}"
        )

    tool_export_types = cast(
        "Iterable[type[ExportPythonToolSentinel]]", union_membership.get(ExportPythonToolSentinel)
    )
    all_tool_results = await MultiGet(
        Get(ExportResult, ExportPythonToolSentinel, request()) for request in tool_export_types
    )

    return ExportResults(venvs + all_tool_results)


def rules():
    return [
        *collect_rules(),
        UnionRule(ExportRequest, ExportVenvsRequest),
    ]
