# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
import os
import uuid
from collections import defaultdict
from dataclasses import dataclass
from enum import Enum
from typing import Any, DefaultDict, Iterable, cast

from pants.backend.python.subsystems.setup import PythonSetup
from pants.backend.python.target_types import PexLayout, PythonResolveField
from pants.backend.python.util_rules.interpreter_constraints import InterpreterConstraints
from pants.backend.python.util_rules.pex import Pex, PexProcess, PexRequest, VenvPex, VenvPexProcess
from pants.backend.python.util_rules.pex_cli import PexPEX
from pants.backend.python.util_rules.pex_environment import PexEnvironment
from pants.backend.python.util_rules.pex_from_targets import RequirementsPexRequest
from pants.backend.python.util_rules.pex_requirements import EntireLockfile, Lockfile
from pants.base.deprecated import warn_or_error
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
from pants.option.option_types import BoolOption, EnumOption
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


@dataclass(frozen=True)
class _ExportVenvForResolveRequest(EngineAwareParameter):
    resolve: str


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


class PythonResolveExportFormat(Enum):
    """How to export Python resolves."""

    mutable_virtualenv = "mutable_virtualenv"
    symlinked_immutable_virtualenv = "symlinked_immutable_virtualenv"


class ExportPluginOptions:
    py_resolve_format = EnumOption(
        default=PythonResolveExportFormat.mutable_virtualenv,
        help=softwrap(
            """\
            Export Python resolves using this format. Options are:
              - mutable_virtualenv: Export a standalone mutable virtualenv that you can
                further modify.
              - symlinked_immutable_virtualenv: Export a symlink into a cached Python virtualenv.
                This virtualenv will have no pip binary, and will be immutable. Any attempt to
                modify it will corrupt the cache!  It may, however, take significantly less time
                to export than a standalone, mutable virtualenv.
            """
        ),
    )

    symlink_python_virtualenv = BoolOption(
        default=False,
        help="Export a symlink into a cached Python virtualenv.  This virtualenv will have no pip binary, "
        "and will be immutable. Any attempt to modify it will corrupt the cache!  It may, however, "
        "take significantly less time to export than a standalone, mutable virtualenv will.",
        removal_version="2.20.0.dev0",
        removal_hint="Set the `[export].py_resolve_format` option to 'symlinked_immutable_virtualenv'",
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
    dest_prefix = (
        os.path.join(req.dest_prefix, path_safe(req.resolve_name))
        if req.resolve_name
        else req.dest_prefix
    )
    # digest_root is the absolute path to build_root/dest_prefix/py_version
    # (py_version may be left off in some cases)
    output_path = "{digest_root}"

    complete_pex_env = pex_env.in_workspace()

    if export_subsys.options.symlink_python_virtualenv:
        export_format = PythonResolveExportFormat.symlinked_immutable_virtualenv
    else:
        export_format = export_subsys.options.py_resolve_format

    if export_format == PythonResolveExportFormat.symlinked_immutable_virtualenv:
        requirements_venv_pex = await Get(VenvPex, PexRequest, req.pex_request)
        py_version = await _get_full_python_version(requirements_venv_pex)
        # Note that for symlinking we ignore qualify_path_with_python_version and always qualify, since
        # we need some name for the symlink anyway.
        dest = f"{dest_prefix}/{py_version}"
        description = (
            f"symlink to immutable virtualenv for {req.resolve_name or 'requirements'} "
            f"(using Python {py_version})"
        )
        venv_abspath = os.path.join(complete_pex_env.pex_root, requirements_venv_pex.venv_rel_dir)
        return ExportResult(
            description,
            dest,
            post_processing_cmds=[
                # export creates an empty directory for us when the digest gets written.
                # We have to remove that before creating the symlink in its place.
                PostProcessingCommand(["rmdir", output_path]),
                PostProcessingCommand(["ln", "-s", venv_abspath, output_path]),
            ],
            resolve=req.resolve_name or None,
        )
    elif export_format == PythonResolveExportFormat.mutable_virtualenv:
        # Note that an internal-only pex will always have the `python` field set.
        # See the build_pex() rule and _determine_pex_python_and_platforms() helper in pex.py.
        requirements_pex = await Get(Pex, PexRequest, req.pex_request)
        assert requirements_pex.python is not None
        py_version = await _get_full_python_version(requirements_pex)
        if req.qualify_path_with_python_version:
            dest = f"{dest_prefix}/{py_version}"
        else:
            dest = dest_prefix
        description = (
            f"mutable virtualenv for {req.resolve_name or 'requirements'} "
            f"(using Python {py_version})"
        )

        merged_digest = await Get(Digest, MergeDigests([pex_pex.digest, requirements_pex.digest]))
        tmpdir_prefix = f".{uuid.uuid4().hex}.tmp"
        tmpdir_under_digest_root = os.path.join("{digest_root}", tmpdir_prefix)
        merged_digest_under_tmpdir = await Get(Digest, AddPrefix(merged_digest, tmpdir_prefix))

        return ExportResult(
            description,
            dest,
            digest=merged_digest_under_tmpdir,
            post_processing_cmds=[
                PostProcessingCommand(
                    complete_pex_env.create_argv(
                        os.path.join(tmpdir_under_digest_root, pex_pex.exe),
                        *[
                            os.path.join(tmpdir_under_digest_root, requirements_pex.name),
                            "venv",
                            "--pip",
                            "--collisions-ok",
                            output_path,
                        ],
                        python=requirements_pex.python,
                    ),
                    {
                        **complete_pex_env.environment_dict(python_configured=True),
                        "PEX_MODULE": "pex.tools",
                    },
                ),
                # Remove the requirements and pex pexes, to avoid confusion.
                PostProcessingCommand(["rm", "-rf", tmpdir_under_digest_root]),
            ],
            resolve=req.resolve_name or None,
        )
    else:
        raise ExportError("Unsupported value for [export].py_resolve_format")


@dataclass(frozen=True)
class MaybeExportResult:
    result: ExportResult | None


@rule
async def export_virtualenv_for_resolve(
    request: _ExportVenvForResolveRequest,
    python_setup: PythonSetup,
    union_membership: UnionMembership,
) -> MaybeExportResult:
    resolve = request.resolve
    lockfile_path = python_setup.resolves.get(resolve)
    if lockfile_path:
        # It's a user resolve.
        lockfile = Lockfile(
            file_path=lockfile_path,
            file_path_description_of_origin=f"the resolve `{resolve}`",
            resolve_name=resolve,
        )

        interpreter_constraints = InterpreterConstraints(
            python_setup.resolves_to_interpreter_constraints.get(
                request.resolve, python_setup.interpreter_constraints
            )
        )

        pex_request = PexRequest(
            description=f"Build pex for resolve `{resolve}`",
            output_filename=f"{path_safe(resolve)}.pex",
            internal_only=True,
            requirements=EntireLockfile(lockfile),
            interpreter_constraints=interpreter_constraints,
            # Packed layout should lead to the best performance in this use case.
            layout=PexLayout.PACKED,
        )
    else:
        # It's a tool resolve.
        # TODO: Can we simplify tool lockfiles to be more uniform with user lockfiles?
        #  It's unclear if we will need the ExportPythonToolSentinel runaround once we
        #  remove the older export codepath below. It would be nice to be able to go from
        #  resolve name -> EntireLockfile, regardless of whether the resolve happened to be
        #  a user lockfile or a tool lockfile. Currently we have to get all the ExportPythonTools
        #  and then check for the resolve name.  But this is OK for now, as it lets us
        #  move towards deprecating that other codepath.
        tool_export_types = cast(
            "Iterable[type[ExportPythonToolSentinel]]",
            union_membership.get(ExportPythonToolSentinel),
        )
        all_export_tool_requests = await MultiGet(
            Get(ExportPythonTool, ExportPythonToolSentinel, tool_export_type())
            for tool_export_type in tool_export_types
        )
        export_tool_request = next(
            (etr for etr in all_export_tool_requests if etr.resolve_name == resolve), None
        )
        if not export_tool_request:
            # No such Python resolve or tool, but it may be a resolve for a different language/backend,
            # so we let the core export goal sort out whether it's an error or not.
            return MaybeExportResult(None)
        if not export_tool_request.pex_request:
            raise ExportError(
                f"Requested an export of `{resolve}` but that tool's exports were disabled with "
                f"the `export=false` option. The per-tool `export=false` options will soon be "
                f"deprecated anyway, so we recommend removing `export=false` from your config file "
                f"and switching to using `--resolve`."
            )
        pex_request = export_tool_request.pex_request

    dest_prefix = os.path.join("python", "virtualenvs")
    export_result = await Get(
        ExportResult,
        VenvExportRequest(
            pex_request,
            dest_prefix,
            resolve,
            qualify_path_with_python_version=True,
        ),
    )
    return MaybeExportResult(export_result)


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
    export_subsys: ExportSubsystem,
) -> ExportResults:
    if export_subsys.options.resolve:
        if request.targets:
            raise ExportError("If using the `--resolve` option, do not also provide target specs.")
        maybe_venvs = await MultiGet(
            Get(MaybeExportResult, _ExportVenvForResolveRequest(resolve))
            for resolve in export_subsys.options.resolve
        )
        return ExportResults(mv.result for mv in maybe_venvs if mv.result is not None)

    # TODO: After the deprecation exipres, everything in this function below this comment
    #  can be deleted.
    warn_or_error(
        "2.23.0.dev0",
        "exporting resolves without using the --resolve option",
        softwrap(
            f"""
            Use the --resolve flag one or more times to name the resolves you want to export,
            and don't provide any target specs. E.g.,

              {bin_name()} export --resolve=python-default --resolve=pytest
            """
        ),
    )
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
