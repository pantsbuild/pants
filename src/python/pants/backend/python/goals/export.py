# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
import os
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, DefaultDict, Iterable, cast

from pants.backend.python.subsystems.setup import PythonSetup
from pants.backend.python.target_types import PythonResolveField
from pants.backend.python.util_rules.interpreter_constraints import InterpreterConstraints
from pants.backend.python.util_rules.pex import Pex, PexProcess, PexRequest, VenvPex, VenvPexProcess
from pants.backend.python.util_rules.pex_cli import PexPEX
from pants.backend.python.util_rules.pex_environment import PexEnvironment
from pants.backend.python.util_rules.pex_from_targets import RequirementsPexRequest
from pants.core.goals.export import (
    Export,
    ExportError,
    ExportRequest,
    ExportResult,
    ExportResults,
    ExportSubsystem,
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
from pants.option.option_types import BoolOption
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


class ExportPluginOptions:
    symlink_python_virtualenv = BoolOption(
        default=False,
        help="Export a symlink into a cached Python virtualenv.  This virtualenv will have no pip binary, "
        "and will be immutable. Any attempt to modify it will corrupt the cache!  It may, however, "
        "take significantly less time to export than a standalone, mutable virtualenv will.",
    )


@rule_helper
async def _get_full_python_version(pex_or_venv_pex: Pex | VenvPex) -> str:
    # Get the full python version (including patch #).
    is_venv_pex = isinstance(pex_or_venv_pex, VenvPex)
    kwargs: dict[str, Any] = dict(
        description="Get interpreter version",
        argv=[
            "-c",
            "import sys; print('.'.join(str(x) for x in sys.version_info[0:3]))",
        ],
        extra_env={"PEX_INTERPRETER": "1"},
    )
    if is_venv_pex:
        kwargs["venv_pex"] = pex_or_venv_pex
        res = await Get(ProcessResult, VenvPexProcess(**kwargs))
    else:
        kwargs["pex"] = pex_or_venv_pex
        res = await Get(ProcessResult, PexProcess(**kwargs))
    return res.stdout.strip().decode()


@dataclass(frozen=True)
class VenvExportRequest:
    pex_request: PexRequest
    dest_prefix: str
    resolve_name: str
    qualify_path_with_python_version: bool


@rule
async def do_export(
    req: VenvExportRequest,
    pex_pex: PexPEX,
    pex_env: PexEnvironment,
    export_subsys: ExportSubsystem,
) -> ExportResult:
    if not req.pex_request.internal_only:
        raise ExportError(f"The PEX to be exported for {req.resolve_name} must be internal_only.")
    dest = (
        os.path.join(req.dest_prefix, path_safe(req.resolve_name))
        if req.resolve_name
        else req.dest_prefix
    )

    complete_pex_env = pex_env.in_workspace()
    if export_subsys.options.symlink_python_virtualenv:
        requirements_venv_pex = await Get(VenvPex, PexRequest, req.pex_request)
        py_version = await _get_full_python_version(requirements_venv_pex)
        # Note that for symlinking we ignore qualify_path_with_python_version and always qualify, since
        # we need some name for the symlink anyway.
        output_path = f"{{digest_root}}/{py_version}"
        description = (
            f"symlink to immutable virtualenv for {req.resolve_name or 'requirements'} "
            f"(using Python {py_version})"
        )
        venv_abspath = os.path.join(complete_pex_env.pex_root, requirements_venv_pex.venv_rel_dir)
        return ExportResult(
            description,
            dest,
            post_processing_cmds=[PostProcessingCommand(["ln", "-s", venv_abspath, output_path])],
        )
    else:
        # Note that an internal-only pex will always have the `python` field set.
        # See the build_pex() rule and _determine_pex_python_and_platforms() helper in pex.py.
        requirements_pex = await Get(Pex, PexRequest, req.pex_request)
        assert requirements_pex.python is not None
        py_version = await _get_full_python_version(requirements_pex)
        output_path = (
            f"{{digest_root}}/{py_version if req.qualify_path_with_python_version else ''}"
        )
        description = (
            f"mutable virtualenv for {req.resolve_name or 'requirements'} "
            f"(using Python {py_version})"
        )

        # NOTE: We add a unique prefix to the pex_pex path to avoid conflicts when multiple
        # venvs are concurrently exporting. Without this prefix all the invocations write
        # the pex_pex to `python/virtualenvs/tools/pex`, and the `rm -f` of the pex_pex
        # path in one export will delete the binary out from under the others.
        pex_pex_dir = f".{req.resolve_name}.tmp"
        pex_pex_digest = await Get(Digest, AddPrefix(pex_pex.digest, pex_pex_dir))
        pex_pex_dest = os.path.join("{digest_root}", pex_pex_dir)

        merged_digest = await Get(Digest, MergeDigests([pex_pex_digest, requirements_pex.digest]))

        return ExportResult(
            description,
            dest,
            digest=merged_digest,
            post_processing_cmds=[
                PostProcessingCommand(
                    complete_pex_env.create_argv(
                        os.path.join(pex_pex_dest, pex_pex.exe),
                        *[
                            os.path.join("{digest_root}", requirements_pex.name),
                            "venv",
                            "--pip",
                            "--collisions-ok",
                            "--remove=pex",
                            output_path,
                        ],
                        python=requirements_pex.python,
                    ),
                    {
                        **complete_pex_env.environment_dict(python_configured=True),
                        "PEX_MODULE": "pex.tools",
                    },
                ),
                # Remove the PEX pex, to avoid confusion.
                PostProcessingCommand(["rm", "-rf", pex_pex_dest]),
            ],
        )


@rule
async def export_virtualenv_for_targets(
    request: _ExportVenvRequest,
    python_setup: PythonSetup,
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

    # Note that a pex created from a RequirementsPexRequest has packed layout,
    # which should lead to the best performance in this use case.
    requirements_pex_request = await Get(
        PexRequest,
        RequirementsPexRequest(
            (tgt.address for tgt in request.root_python_targets),
            hardcoded_interpreter_constraints=interpreter_constraints,
        ),
    )

    dest_prefix = (
        os.path.join("python", "virtualenvs")
        if request.resolve
        else os.path.join("python", "virtualenv")
    )

    export_result = await Get(
        ExportResult,
        VenvExportRequest(
            requirements_pex_request,
            dest_prefix,
            request.resolve or "",
            qualify_path_with_python_version=True,
        ),
    )
    return export_result


@rule
async def export_tool(request: ExportPythonTool) -> ExportResult:
    assert request.pex_request is not None

    export_result = await Get(
        ExportResult,
        VenvExportRequest(
            request.pex_request,
            # TODO: It seems unnecessary to qualify with "tools", since the tool resolve names don't collide
            #  with user resolve names.  We should get rid of this via a deprecation cycle.
            os.path.join("python", "virtualenvs", "tools"),
            request.resolve_name,
            # TODO: It is pretty ad-hoc that we do add the interpreter version for resolves but not for tools.
            #  We should pick one and deprecate the other.
            qualify_path_with_python_version=False,
        ),
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
        Export.subsystem_cls.register_plugin_options(ExportPluginOptions),
        UnionRule(ExportRequest, ExportVenvsRequest),
    ]
