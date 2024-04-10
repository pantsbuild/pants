# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import dataclasses
import logging
import os
import uuid
from dataclasses import dataclass
from enum import Enum
from typing import Any, cast

from pants.backend.python.subsystems.python_tool_base import PythonToolBase
from pants.backend.python.subsystems.setup import PythonSetup
from pants.backend.python.target_types import PexLayout
from pants.backend.python.util_rules.interpreter_constraints import InterpreterConstraints
from pants.backend.python.util_rules.local_dists_pep660 import (
    EditableLocalDists,
    EditableLocalDistsRequest,
)
from pants.backend.python.util_rules.pex import Pex, PexProcess, PexRequest, VenvPex, VenvPexProcess
from pants.backend.python.util_rules.pex_cli import PexPEX
from pants.backend.python.util_rules.pex_environment import PexEnvironment
from pants.backend.python.util_rules.pex_requirements import EntireLockfile, Lockfile
from pants.core.goals.export import (
    Export,
    ExportError,
    ExportRequest,
    ExportResult,
    ExportResults,
    ExportSubsystem,
    PostProcessingCommand,
)
from pants.core.goals.resolves import ExportableTool
from pants.engine.engine_aware import EngineAwareParameter
from pants.engine.internals.native_engine import AddPrefix, Digest, MergeDigests, Snapshot
from pants.engine.internals.selectors import Get, MultiGet
from pants.engine.process import ProcessCacheScope, ProcessResult
from pants.engine.rules import collect_rules, rule
from pants.engine.unions import UnionMembership, UnionRule
from pants.option.option_types import EnumOption, StrListOption
from pants.util.strutil import path_safe, softwrap

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ExportVenvsRequest(ExportRequest):
    pass


@dataclass(frozen=True)
class _ExportVenvForResolveRequest(EngineAwareParameter):
    resolve: str


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
              - `mutable_virtualenv`: Export a standalone mutable virtualenv that you can
                further modify.
              - `symlinked_immutable_virtualenv`: Export a symlink into a cached Python virtualenv.
                This virtualenv will have no pip binary, and will be immutable. Any attempt to
                modify it will corrupt the cache! It may, however, take significantly less time
                to export than a standalone, mutable virtualenv.
            """
        ),
    )

    py_editable_in_resolve = StrListOption(
        # TODO: Is there a way to get [python].resolves in a memoized_property here?
        #       If so, then we can validate that all resolves here are defined there.
        help=softwrap(
            """
            When exporting a mutable virtualenv for a resolve, do PEP-660 editable installs
            of all 'python_distribution' targets that own code in the exported resolve.

            If a resolve name is not in this list, 'python_distribution' targets will not
            be installed in the virtualenv. This defaults to an empty list for backwards
            compatibility and to prevent unnecessary work to generate and install the
            PEP-660 editable wheels.

            This only applies when '[python].enable_resolves' is true and when exporting a
            'mutable_virtualenv' ('symlinked_immutable_virtualenv' exports are not "full"
            virtualenvs because they must not be edited, and do not include 'pip').

            NOTE: If you are using legacy exports (not using the '--resolve' option), then
            this option has no effect. Legacy exports will not include any editable installs.
            """
        ),
        advanced=True,
    )


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
    editable_local_dists_digest: Digest | None = None


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

    export_format = export_subsys.options.py_resolve_format

    if export_format == PythonResolveExportFormat.symlinked_immutable_virtualenv:
        # NB: The symlink performance hack leaks an internal named cache location as output (via
        #  the symlink target). If the user partially or fully deletes the named cache, the symlink
        #  target might point to a malformed venv, or it might not exist at all.
        #  To prevent returning a symlink to a busted or nonexistent venv from a cached process
        #  (or a memoized rule) we force the process to rerun per-session.
        #  This does mean re-running the process superfluously when the named cache is intact, but
        #  that is generally fast, since all wheels are already cached, and it's best to be safe.
        requirements_venv_pex = await Get(
            VenvPex,
            PexRequest,
            dataclasses.replace(req.pex_request, cache_scope=ProcessCacheScope.PER_SESSION),
        )
        py_version = await _get_full_python_version(requirements_venv_pex)
        # Note that for symlinking we ignore qualify_path_with_python_version and always qualify,
        # since we need some name for the symlink anyway.
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

        post_processing_cmds = [
            PostProcessingCommand(
                complete_pex_env.create_argv(
                    os.path.join(tmpdir_under_digest_root, pex_pex.exe),
                    *(
                        os.path.join(tmpdir_under_digest_root, requirements_pex.name),
                        "venv",
                        "--pip",
                        "--collisions-ok",
                        output_path,
                    ),
                ),
                {
                    **complete_pex_env.environment_dict(python=requirements_pex.python),
                    "PEX_MODULE": "pex.tools",
                },
            ),
            # Remove the requirements and pex pexes, to avoid confusion.
            PostProcessingCommand(["rm", "-rf", tmpdir_under_digest_root]),
        ]

        # Insert editable wheel post-processing commands if needed.
        if req.editable_local_dists_digest is not None:
            # We need the snapshot to get the wheel file names which are something like:
            #   - pkg_name-1.2.3-0.editable-py3-none-any.whl
            wheels_snapshot = await Get(Snapshot, Digest, req.editable_local_dists_digest)
            # We need the paths to the installed .dist-info directories to finish installation.
            py_major_minor_version = ".".join(py_version.split(".", 2)[:2])
            lib_dir = os.path.join(
                output_path, "lib", f"python{py_major_minor_version}", "site-packages"
            )
            dist_info_dirs = [
                # This builds: dist/.../resolve/3.8.9/lib/python3.8/site-packages/pkg_name-1.2.3.dist-info
                os.path.join(lib_dir, "-".join(f.split("-")[:2]) + ".dist-info")
                for f in wheels_snapshot.files
            ]
            # We use slice assignment to insert multiple elements at index 1.
            post_processing_cmds[1:1] = [
                PostProcessingCommand(
                    [
                        # The wheels are "sources" in the pex and get dumped in lib_dir
                        # so we move them to tmpdir where they will be removed at the end.
                        "mv",
                        *(os.path.join(lib_dir, f) for f in wheels_snapshot.files),
                        tmpdir_under_digest_root,
                    ]
                ),
                PostProcessingCommand(
                    [
                        # Now install the editable wheels.
                        os.path.join(output_path, "bin", "pip"),
                        "install",
                        "--no-deps",  # The deps were already installed via requirements.pex.
                        "--no-build-isolation",  # Avoid VCS dep downloads (as they are installed).
                        *(os.path.join(tmpdir_under_digest_root, f) for f in wheels_snapshot.files),
                    ]
                ),
                PostProcessingCommand(
                    [
                        # Replace pip's direct_url.json (which points to the temp editable wheel)
                        # with ours (which points to build_dir sources and is marked "editable").
                        # Also update INSTALLER file to indicate that pants installed it.
                        "sh",
                        "-c",
                        " ".join(
                            [
                                f"mv -f {src} {dst}; echo pants > {installer};"
                                for src, dst, installer in zip(
                                    [
                                        os.path.join(d, "direct_url__pants__.json")
                                        for d in dist_info_dirs
                                    ],
                                    [os.path.join(d, "direct_url.json") for d in dist_info_dirs],
                                    [os.path.join(d, "INSTALLER") for d in dist_info_dirs],
                                )
                            ]
                        ),
                    ]
                ),
            ]

        return ExportResult(
            description,
            dest,
            digest=merged_digest_under_tmpdir,
            post_processing_cmds=post_processing_cmds,
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
    export_subsys: ExportSubsystem,
    union_membership: UnionMembership,
) -> MaybeExportResult:
    resolve = request.resolve
    lockfile_path = python_setup.resolves.get(resolve)
    if lockfile_path:
        lockfile = Lockfile(
            url=lockfile_path,
            url_description_of_origin=f"the resolve `{resolve}`",
            resolve_name=resolve,
        )
    else:
        maybe_exportable = ExportableTool.filter_for_subclasses(
            union_membership, PythonToolBase
        ).get(resolve)
        if maybe_exportable:
            lockfile = cast(
                PythonToolBase, maybe_exportable
            ).pex_requirements_for_default_lockfile()
        else:
            lockfile = None

    if not lockfile:
        raise ExportError(
            f"No resolve named {resolve} found in [{python_setup.options_scope}].resolves."
        )

    interpreter_constraints = InterpreterConstraints(
        python_setup.resolves_to_interpreter_constraints.get(
            request.resolve, python_setup.interpreter_constraints
        )
    )

    if resolve in export_subsys.options.py_editable_in_resolve:
        editable_local_dists = await Get(
            EditableLocalDists, EditableLocalDistsRequest(resolve=resolve)
        )
        editable_local_dists_digest = editable_local_dists.optional_digest
    else:
        editable_local_dists_digest = None

    pex_request = PexRequest(
        description=f"Build pex for resolve `{resolve}`",
        output_filename=f"{path_safe(resolve)}.pex",
        internal_only=True,
        requirements=EntireLockfile(lockfile),
        sources=editable_local_dists_digest,
        interpreter_constraints=interpreter_constraints,
        # Packed layout should lead to the best performance in this use case.
        layout=PexLayout.PACKED,
    )

    dest_prefix = os.path.join("python", "virtualenvs")
    export_result = await Get(
        ExportResult,
        VenvExportRequest(
            pex_request,
            dest_prefix,
            resolve,
            qualify_path_with_python_version=True,
            editable_local_dists_digest=editable_local_dists_digest,
        ),
    )
    return MaybeExportResult(export_result)


@rule
async def export_virtualenvs(
    request: ExportVenvsRequest,
    export_subsys: ExportSubsystem,
) -> ExportResults:
    if not export_subsys.options.resolve:
        raise ExportError("Must specify at least one --resolve to export")
    if request.targets:
        raise ExportError("The `export` goal does not take target specs.")
    maybe_venvs = await MultiGet(
        Get(MaybeExportResult, _ExportVenvForResolveRequest(resolve))
        for resolve in export_subsys.options.resolve
    )
    return ExportResults(mv.result for mv in maybe_venvs if mv.result is not None)


def rules():
    return [
        *collect_rules(),
        Export.subsystem_cls.register_plugin_options(ExportPluginOptions),
        UnionRule(ExportRequest, ExportVenvsRequest),
    ]
