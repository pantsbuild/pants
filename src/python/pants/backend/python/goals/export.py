# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import dataclasses
import logging
import os
import textwrap
import uuid
from dataclasses import dataclass
from enum import Enum
from typing import cast

from pants.backend.python.subsystems.python_tool_base import PythonToolBase
from pants.backend.python.subsystems.setup import PythonSetup
from pants.backend.python.target_types import PexLayout, PythonResolveField, PythonSourceField
from pants.backend.python.util_rules.interpreter_constraints import InterpreterConstraints
from pants.backend.python.util_rules.local_dists_pep660 import (
    EditableLocalDists,
    EditableLocalDistsRequest,
)
from pants.backend.python.util_rules.pex import Pex, PexRequest, VenvPex
from pants.backend.python.util_rules.pex_cli import PexPEX
from pants.backend.python.util_rules.pex_environment import PexEnvironment, PythonExecutable
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
from pants.core.util_rules.source_files import SourceFiles
from pants.core.util_rules.stripped_source_files import StrippedSourceFiles
from pants.engine.engine_aware import EngineAwareParameter
from pants.engine.fs import CreateDigest, FileContent
from pants.engine.internals.native_engine import (
    EMPTY_DIGEST,
    AddPrefix,
    Digest,
    MergeDigests,
    Snapshot,
)
from pants.engine.internals.selectors import Get, MultiGet
from pants.engine.process import Process, ProcessCacheScope, ProcessResult
from pants.engine.rules import collect_rules, rule
from pants.engine.target import AllTargets, HydratedSources, HydrateSourcesRequest, SourcesField
from pants.engine.unions import UnionMembership, UnionRule
from pants.option.option_types import BoolOption, EnumOption, StrListOption
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
            of all `python_distribution` targets that own code in the exported resolve.

            If a resolve name is not in this list, `python_distribution` targets will not
            be installed in the virtualenv. This defaults to an empty list for backwards
            compatibility and to prevent unnecessary work to generate and install the
            PEP-660 editable wheels.

            This only applies when `[python].enable_resolves` is true and when exporting a
            `mutable_virtualenv` (`symlinked_immutable_virtualenv` exports are not "full"
            virtualenvs because they must not be edited, and do not include `pip`).
            """
        ),
        advanced=True,
    )

    py_hermetic_scripts = BoolOption(
        default=True,
        help=softwrap(
            """
            When exporting a mutable virtualenv for a resolve, by default
            modify console script shebang lines to make them "hermetic".
            The shebang of hermetic console scripts uses the python args: `-sE`:

              - `-s` skips inclusion of the user site-packages directory,
              - `-E` ignores all `PYTHON*` env vars like `PYTHONPATH`.

            Set this to false if you need non-hermetic scripts with
            simple python shebangs that respect vars like `PYTHONPATH`,
            to, for example, allow IDEs like PyCharm to inject its debugger,
            coverage, or other IDE-specific libs when running a script.

            This only applies when when exporting a `mutable_virtualenv`
            (`symlinked_immutable_virtualenv` exports are not "full"
            virtualenvs because they are used internally by pants itself.
            Pants requires hermetic scripts to provide its reproduciblity
            guarantee, fine-grained caching, and other features).
            """
        ),
        advanced=True,
        removal_version="2.24.0.dev0",
        removal_hint=softwrap(
            """
            Use `--export-py-non-hermetic-scripts-in-resolve` instead.
            """
        ),
    )

    py_non_hermetic_scripts_in_resolve = StrListOption(
        help=softwrap(
            """
            When exporting a mutable virtualenv for a resolve listed in this option, by default
            console script shebang lines will be made "hermetic". Specifically, the shebang of
            hermetic console scripts will uses the python args `-sE` where:

              - `-s` skips inclusion of the user site-packages directory,
              - `-E` ignores all `PYTHON*` env vars like `PYTHONPATH`.

            If you need "non-hermetic" scripts for a partcular resolve, then add that resolve's name
            to this option. This will allow simple python shebangs that respect vars like
            `PYTHONPATH`, which, for example, will allow IDEs like PyCharm to inject its debugger,
            coverage, or other IDE-specific libs when running a script.

            This only applies when when exporting a `mutable_virtualenv`
            (`symlinked_immutable_virtualenv` exports are not "full"
            virtualenvs because they are used internally by pants itself.
            Pants requires hermetic scripts to provide its reproduciblity
            guarantee, fine-grained caching, and other features).
            """
        ),
        advanced=True,
    )

    py_generated_sources_in_resolve = StrListOption(
        help=softwrap(
            """
            When exporting a mutable virtualenv for a resolve listed in this option, generate sources which result from
            code generation (for example, the `protobuf_sources` and `thrift_sources` target types) into the mutable
            virtualenv exported for that resolve. Generated sources will be placed in the appropriate location within
            the site-packages directory of the mutable virtualenv.
            """
        )
    )


async def _get_full_python_version(python: PythonExecutable) -> str:
    # Get the full python version (including patch #).
    argv = [
        python.path,
        "-c",
        "import sys; print('.'.join(str(x) for x in sys.version_info[0:3]))",
    ]
    res = await Get(ProcessResult, Process(argv, description="Get interpreter version"))
    return res.stdout.strip().decode()


@dataclass(frozen=True)
class VenvExportRequest:
    py_version: str
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
        # Note that for symlinking we ignore qualify_path_with_python_version and always qualify,
        # since we need some name for the symlink anyway.
        dest = f"{dest_prefix}/{req.py_version}"
        description = (
            f"symlink to immutable virtualenv for {req.resolve_name or 'requirements'} "
            f"(using Python {req.py_version})"
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
        if req.qualify_path_with_python_version:
            dest = f"{dest_prefix}/{req.py_version}"
        else:
            dest = dest_prefix
        description = (
            f"mutable virtualenv for {req.resolve_name or 'requirements'} "
            f"(using Python {req.py_version})"
        )

        merged_digest = await Get(Digest, MergeDigests([pex_pex.digest, requirements_pex.digest]))
        tmpdir_prefix = f".{uuid.uuid4().hex}.tmp"
        tmpdir_under_digest_root = os.path.join("{digest_root}", tmpdir_prefix)
        merged_digest_under_tmpdir = await Get(Digest, AddPrefix(merged_digest, tmpdir_prefix))

        venv_prompt = f"{req.resolve_name}/{req.py_version}" if req.resolve_name else req.py_version

        pex_args = [
            os.path.join(tmpdir_under_digest_root, requirements_pex.name),
            "venv",
            "--pip",
            "--collisions-ok",
            f"--prompt={venv_prompt}",
            output_path,
        ]
        if (
            not export_subsys.options.py_hermetic_scripts
            or req.resolve_name in export_subsys.options.py_non_hermetic_scripts_in_resolve
        ):
            pex_args.insert(-1, "--non-hermetic-scripts")

        post_processing_cmds = [
            PostProcessingCommand(
                complete_pex_env.create_argv(
                    os.path.join(tmpdir_under_digest_root, pex_pex.exe),
                    *pex_args,
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
            py_major_minor_version = ".".join(req.py_version.split(".", 2)[:2])
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


@dataclass(frozen=True)
class _ExportPythonCodegenRequest:
    resolve: str


@dataclass(frozen=True)
class _ExportPythonCodegenResult:
    digest: Digest


@dataclass(frozen=True)
class _ExportPythonCodegenSetup:
    PKG_DIR = "__pants_codegen__"
    SCRIPT_NAME = "codegen_setup.py"

    setup_script_digest: Digest


@rule
async def python_codegen_export_setup() -> _ExportPythonCodegenSetup:
    codegen_setup_script_digest = await Get(
        Digest,
        CreateDigest(
            [
                FileContent(
                    path=f"{_ExportPythonCodegenSetup.PKG_DIR}/{_ExportPythonCodegenSetup.SCRIPT_NAME}",
                    is_executable=True,
                    content=textwrap.dedent(
                        f"""\
                        import os
                        import site
                        import sys

                        site_packages_dirs = site.getsitepackages()
                        if not site_packages_dirs:
                            raise Exception("Unable to determine location of site-packages directory in venv.")
                        site_packages_dir = site_packages_dirs[0]

                        codegen_dir = sys.argv[1]

                        for item in os.listdir(codegen_dir):
                            if item == "{_ExportPythonCodegenSetup.SCRIPT_NAME}":
                                continue
                            os.rename(os.path.join(codegen_dir, item), os.path.join(site_packages_dir, item))
                        """
                    ).encode(),
                )
            ]
        ),
    )

    return _ExportPythonCodegenSetup(codegen_setup_script_digest)


@rule
async def export_python_codegen(
    request: _ExportPythonCodegenRequest, python_setup: PythonSetup, all_targets: AllTargets
) -> _ExportPythonCodegenResult:
    non_python_sources_in_python_resolve = [
        tgt.get(SourcesField)
        for tgt in all_targets
        if tgt.has_field(PythonResolveField)
        and tgt[PythonResolveField].normalized_value(python_setup) == request.resolve
        and tgt.has_field(SourcesField)
        and not tgt.has_field(PythonSourceField)
    ]

    if not non_python_sources_in_python_resolve:
        return _ExportPythonCodegenResult(EMPTY_DIGEST)

    hydrated_non_python_sources = await MultiGet(
        Get(
            HydratedSources,
            HydrateSourcesRequest(
                sources,
                for_sources_types=(PythonSourceField,),
                enable_codegen=True,
            ),
        )
        for sources in non_python_sources_in_python_resolve
    )

    merged_snapshot = await Get(
        Snapshot,
        MergeDigests(
            hydrated_sources.snapshot.digest for hydrated_sources in hydrated_non_python_sources
        ),
    )

    stripped_source_files = await Get(StrippedSourceFiles, SourceFiles(merged_snapshot, ()))

    return _ExportPythonCodegenResult(stripped_source_files.snapshot.digest)


# Generate codegen Python sources and add them to the virtualenv to be exported.
async def add_codegen_to_export_result(
    resolve: str, export_result: ExportResult, codegen_setup: _ExportPythonCodegenSetup
) -> ExportResult:
    # Generate Python sources from codegen targets in this resolve.
    codegen_result = await Get(
        _ExportPythonCodegenResult, _ExportPythonCodegenRequest(resolve=resolve)
    )
    if codegen_result.digest == EMPTY_DIGEST:
        return export_result

    codegen_digest = await Get(
        Digest, AddPrefix(codegen_result.digest, _ExportPythonCodegenSetup.PKG_DIR)
    )

    export_digest_with_codegen = await Get(
        Digest,
        MergeDigests([export_result.digest, codegen_digest, codegen_setup.setup_script_digest]),
    )

    pkg_dir_path = os.path.join(
        "{digest_root}",
        _ExportPythonCodegenSetup.PKG_DIR,
    )
    script_path = os.path.join(pkg_dir_path, _ExportPythonCodegenSetup.SCRIPT_NAME)

    codegen_post_processing_cmds = (
        PostProcessingCommand(
            [
                os.path.join("{digest_root}", "bin", "python"),
                script_path,
                pkg_dir_path,
            ]
        ),
        PostProcessingCommand(["rm", script_path]),
        PostProcessingCommand(["rmdir", pkg_dir_path]),
    )

    return dataclasses.replace(
        export_result,
        digest=export_digest_with_codegen,
        post_processing_cmds=export_result.post_processing_cmds + codegen_post_processing_cmds,
    )


@rule
async def export_virtualenv_for_resolve(
    request: _ExportVenvForResolveRequest,
    python_setup: PythonSetup,
    export_subsys: ExportSubsystem,
    union_membership: UnionMembership,
    codegen_setup: _ExportPythonCodegenSetup,
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
        return MaybeExportResult(None)

    interpreter_constraints = InterpreterConstraints(
        python_setup.resolves_to_interpreter_constraints.get(
            request.resolve, python_setup.interpreter_constraints
        )
    )

    python = await Get(PythonExecutable, InterpreterConstraints, interpreter_constraints)
    py_version = await _get_full_python_version(python)

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
        python=python,
        # Packed layout should lead to the best performance in this use case.
        layout=PexLayout.PACKED,
    )

    dest_prefix = os.path.join("python", "virtualenvs")
    export_result = await Get(
        ExportResult,
        VenvExportRequest(
            py_version,
            pex_request,
            dest_prefix,
            resolve,
            qualify_path_with_python_version=True,
            editable_local_dists_digest=editable_local_dists_digest,
        ),
    )

    # Add generated Python sources from codegen targets to the mutable virtualenv.
    if (
        resolve in export_subsys.options.py_generated_sources_in_resolve
        and export_subsys.options.py_resolve_format == PythonResolveExportFormat.mutable_virtualenv
    ):
        export_result = await add_codegen_to_export_result(
            request.resolve, export_result, codegen_setup
        )

    return MaybeExportResult(export_result)


@rule
async def export_virtualenvs(
    request: ExportVenvsRequest,
    export_subsys: ExportSubsystem,
) -> ExportResults:
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
