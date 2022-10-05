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
from pants.engine.environment import EnvironmentName
from pants.engine.internals.native_engine import AddPrefix, Digest, MergeDigests
from pants.engine.internals.selectors import Get, MultiGet
from pants.engine.process import ProcessResult
from pants.engine.rules import collect_rules, rule, rule_helper
from pants.engine.target import Target
from pants.engine.unions import UnionMembership, UnionRule, union
from pants.util.docutil import bin_name
from pants.util.strutil import path_safe, softwrap

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


@union(in_scope_types=[EnvironmentName])
class ExportPythonToolSentinel:
    """Python tools use this as an entry point to say how to export their tool virtualenv.

    Each tool should subclass `ExportPythonToolSentinel` and set up a rule that goes from
    the subclass -> `ExportPythonTool`. Register a union rule for the `ExportPythonToolSentinel`
    subclass.

    If the tool is in `pantsbuild/pants`, update `export_integration_test.py`.
    """


@dataclass(frozen=True)
class ExportPythonTool(EngineAwareParameter):
    """How to export a particular Python tool.

    If `pex_request=None`, the tool will be skipped.
    """

    resolve_name: str
    pex_request: PexRequest | None

    def debug_hint(self) -> str | None:
        return self.resolve_name


@rule_helper
async def _do_export(
    requirements_pex: Pex,
    pex_pex: PexPEX,
    dest: str,
    resolve_name: str,
    qualify_path_with_python_version: bool,
) -> ExportResult:
    # Get the path to the interpreter, and the full python version (including patch #).
    res = await Get(
        ProcessResult,
        PexProcess(
            pex=requirements_pex,
            description="Get interpreter path and version",
            argv=[
                "-c",
                "import sys; print(sys.executable); print('.'.join(str(x) for x in sys.version_info[0:3]))",
            ],
            extra_env={"PEX_INTERPRETER": "1"},
        ),
    )
    interpreter_path, py_version = res.stdout.strip().decode().split("\n")

    # NOTE: We add a unique prefix to the pex_pex path to avoid conflicts when multiple
    # venvs are concurrently exporting. Without this prefix all the invocations write
    # the pex_pex to `python/virtualenvs/tools/pex`, and the `rm -f` of the pex_pex
    # path in one export will delete the binary out from under the others.
    pex_pex_dir = f".{resolve_name}.tmp"
    pex_pex_digest = await Get(Digest, AddPrefix(pex_pex.digest, pex_pex_dir))
    pex_pex_dest = os.path.join("{digest_root}", pex_pex_dir)

    merged_digest = await Get(Digest, MergeDigests([pex_pex_digest, requirements_pex.digest]))

    description = f"for {resolve_name} " if resolve_name else ""
    return ExportResult(
        f"virtualenv {description}(using Python {py_version})",
        dest,
        digest=merged_digest,
        post_processing_cmds=[
            PostProcessingCommand(
                [
                    interpreter_path,
                    os.path.join(pex_pex_dest, pex_pex.exe),
                    os.path.join("{digest_root}", requirements_pex.name),
                    "venv",
                    "--pip",
                    "--collisions-ok",
                    "--remove=all",
                    f"{{digest_root}}/{py_version if qualify_path_with_python_version else ''}",
                ],
                {"PEX_MODULE": "pex.tools"},
            ),
            # Remove the PEX pex, to avoid confusion.
            PostProcessingCommand(["rm", "-rf", pex_pex_dest]),
        ],
    )


@rule
async def export_virtualenv_for_targets(
    request: _ExportVenvRequest,
    python_setup: PythonSetup,
    pex_pex: PexPEX,
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

    # Note that a pex created from a RequirementsPexRequest has packed layout, which should lead
    # to the best performance in this use case.
    requirements_pex = await Get(
        Pex,
        RequirementsPexRequest(
            (tgt.address for tgt in request.root_python_targets),
            hardcoded_interpreter_constraints=interpreter_constraints,
        ),
    )

    dest = (
        os.path.join("python", "virtualenvs", path_safe(request.resolve))
        if request.resolve
        else os.path.join("python", "virtualenv")
    )

    export_result = await _do_export(
        requirements_pex,
        pex_pex,
        dest,
        request.resolve or "",
        qualify_path_with_python_version=True,
    )
    return export_result


@rule
async def export_tool(request: ExportPythonTool, pex_pex: PexPEX) -> ExportResult:
    assert request.pex_request is not None
    if not request.pex_request.internal_only:
        raise ExportError(f"The PexRequest for {request.resolve_name} must be internal_only.")

    # TODO: It seems unnecessary to qualify with "tools", since the tool resolve names don't collide
    #  with user resolve names.  We should get rid of this via a deprecation cycle.
    dest = os.path.join("python", "virtualenvs", "tools", request.resolve_name)
    pex = await Get(Pex, PexRequest, request.pex_request)
    export_result = await _do_export(
        pex,
        pex_pex,
        dest,
        request.resolve_name,
        # TODO: It is pretty ad-hoc that we do add the interpreter version for resolves but not for tools.
        #  We should pick one and deprecate the other.
        qualify_path_with_python_version=False,
    )
    return export_result


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
            softwrap(
                f"""
                Because `[python].enable_resolves` is true, `{bin_name()} export ::` no longer
                writes virtualenvs to {no_resolves_dest}, but instead underneath
                {dist_dir.relpath / 'python' / 'virtualenvs'}. You will need to
                update your IDE to point to the new virtualenv.

                To silence this error, delete {no_resolves_dest}
                """
            )
        )

    tool_export_types = cast(
        "Iterable[type[ExportPythonToolSentinel]]", union_membership.get(ExportPythonToolSentinel)
    )
    # TODO: We request the `ExportPythonTool` entries independently of the `ExportResult`s because
    # inlining the request causes a rule graph issue. Revisit after #11269.
    all_export_tool_requests = await MultiGet(
        Get(ExportPythonTool, ExportPythonToolSentinel, tool_export_type())
        for tool_export_type in tool_export_types
    )
    all_tool_results = await MultiGet(
        Get(ExportResult, ExportPythonTool, request)
        for request in all_export_tool_requests
        if request.pex_request is not None
    )

    return ExportResults(venvs + all_tool_results)


def rules():
    return [
        *collect_rules(),
        UnionRule(ExportRequest, ExportVenvsRequest),
    ]
