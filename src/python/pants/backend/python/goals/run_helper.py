# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import dataclasses
import os
import textwrap
from typing import Iterable, Optional

from pants.backend.python.subsystems.debugpy import DebugPy
from pants.backend.python.target_types import (
    ConsoleScript,
    Executable,
    PexEntryPointField,
    ResolvedPexEntryPoint,
    ResolvePexEntryPointRequest,
)
from pants.backend.python.util_rules.interpreter_constraints import InterpreterConstraints
from pants.backend.python.util_rules.pex import Pex, PexRequest, VenvPex, VenvPexRequest
from pants.backend.python.util_rules.pex_environment import PexEnvironment, PythonExecutable
from pants.backend.python.util_rules.pex_from_targets import PexFromTargetsRequest
from pants.backend.python.util_rules.python_sources import (
    PythonSourceFiles,
    PythonSourceFilesRequest,
)
from pants.core.goals.run import RunDebugAdapterRequest, RunRequest
from pants.core.subsystems.debug_adapter import DebugAdapterSubsystem
from pants.engine.addresses import Address
from pants.engine.fs import CreateDigest, Digest, FileContent, MergeDigests
from pants.engine.rules import Get, MultiGet
from pants.engine.target import TransitiveTargets, TransitiveTargetsRequest
from pants.util.frozendict import FrozenDict


def _in_chroot(relpath: str) -> str:
    return os.path.join("{chroot}", relpath)


async def _create_python_source_run_request(
    address: Address,
    *,
    entry_point_field: PexEntryPointField,
    pex_env: PexEnvironment,
    run_in_sandbox: bool,
    pex_path: Iterable[Pex] = (),
    console_script: Optional[ConsoleScript] = None,
    executable: Optional[Executable] = None,
) -> RunRequest:
    addresses = [address]
    entry_point, transitive_targets = await MultiGet(
        Get(
            ResolvedPexEntryPoint,
            ResolvePexEntryPointRequest(entry_point_field),
        ),
        Get(TransitiveTargets, TransitiveTargetsRequest(addresses)),
    )

    pex_filename = (
        address.generated_name.replace(".", "_") if address.generated_name else address.target_name
    )

    pex_request, sources = await MultiGet(
        Get(
            PexRequest,
            PexFromTargetsRequest(
                addresses,
                output_filename=f"{pex_filename}.pex",
                internal_only=True,
                include_source_files=False,
                include_local_dists=True,
                # `PEX_EXTRA_SYS_PATH` should contain this entry_point's module.
                main=executable or console_script or entry_point.val,
                additional_args=(
                    # N.B.: Since we cobble together the runtime environment via PEX_EXTRA_SYS_PATH
                    # below, it's important for any app that re-executes itself that these environment
                    # variables are not stripped.
                    "--no-strip-pex-env",
                ),
            ),
        ),
        Get(
            PythonSourceFiles,
            PythonSourceFilesRequest(transitive_targets.closure, include_files=True),
        ),
    )

    pex_request = dataclasses.replace(pex_request, pex_path=(*pex_request.pex_path, *pex_path))

    if run_in_sandbox:
        # Note that a RunRequest always expects to run directly in the sandbox/workspace
        # root, hence working_directory=None.
        complete_pex_environment = pex_env.in_sandbox(working_directory=None)
    else:
        complete_pex_environment = pex_env.in_workspace()
    venv_pex, python = await MultiGet(
        Get(VenvPex, VenvPexRequest(pex_request, complete_pex_environment)),
        Get(PythonExecutable, InterpreterConstraints, pex_request.interpreter_constraints),
    )
    input_digests = [
        venv_pex.digest,
        # Note regarding not-in-sandbox mode: You might think that the sources don't need to be copied
        # into the chroot when using inline sources. But they do, because some of them might be
        # codegenned, and those won't exist in the inline source tree. Rather than incurring the
        # complexity of figuring out here which sources were codegenned, we copy everything.
        # The inline source roots precede the chrooted ones in PEX_EXTRA_SYS_PATH, so the inline
        # sources will take precedence and their copies in the chroot will be ignored.
        sources.source_files.snapshot.digest,
    ]
    merged_digest = await Get(Digest, MergeDigests(input_digests))

    chrooted_source_roots = [_in_chroot(sr) for sr in sources.source_roots]
    # The order here is important: we want the in-repo sources to take precedence over their
    # copies in the sandbox (see above for why those copies exist even in non-sandboxed mode).
    source_roots = [
        *([] if run_in_sandbox else sources.source_roots),
        *chrooted_source_roots,
    ]
    extra_env = {
        **complete_pex_environment.environment_dict(python=python),
        "PEX_EXTRA_SYS_PATH": os.pathsep.join(source_roots),
    }
    append_only_caches = (
        FrozenDict({}) if venv_pex.append_only_caches is None else venv_pex.append_only_caches
    )

    return RunRequest(
        digest=merged_digest,
        args=[_in_chroot(venv_pex.pex.argv0)],
        extra_env=extra_env,
        append_only_caches={
            **complete_pex_environment.append_only_caches,
            **append_only_caches,
        },
    )


async def _create_python_source_run_dap_request(
    regular_run_request: RunRequest,
    *,
    debugpy: DebugPy,
    debug_adapter: DebugAdapterSubsystem,
    run_in_sandbox: bool,
) -> RunDebugAdapterRequest:
    launcher_digest = await Get(
        Digest,
        CreateDigest(
            [
                FileContent(
                    "__debugpy_launcher.py",
                    textwrap.dedent(
                        """
                            import os
                            CHROOT = os.environ["PANTS_CHROOT"]

                            del os.environ["PEX_INTERPRETER"]

                            import debugpy._vendored.force_pydevd
                            from _pydevd_bundle.pydevd_process_net_command_json import PyDevJsonCommandProcessor
                            orig_resolve_remote_root = PyDevJsonCommandProcessor._resolve_remote_root

                            def patched_resolve_remote_root(self, local_root, remote_root):
                                if remote_root == ".":
                                    remote_root = CHROOT
                                return orig_resolve_remote_root(self, local_root, remote_root)

                            PyDevJsonCommandProcessor._resolve_remote_root = patched_resolve_remote_root

                            from debugpy.server import cli
                            cli.main()
                            """
                    ).encode("utf-8"),
                ),
            ]
        ),
    )

    merged_digest = await Get(
        Digest,
        MergeDigests(
            [
                regular_run_request.digest,
                launcher_digest,
            ]
        ),
    )
    extra_env = dict(regular_run_request.extra_env)
    extra_env["PEX_INTERPRETER"] = "1"
    # See https://github.com/pantsbuild/pants/issues/17540
    # and https://github.com/pantsbuild/pants/issues/18243
    # For `run --debug-adapter`, the client might send a `pathMappings`
    # (this is likely as VS Code likes to configure that by default) with a `remoteRoot` of ".".
    #
    # For `run`, CWD is the build root. If `run_in_sandbox` is False, everything is OK.
    # If `run_in_sandbox` is True, breakpoints won't be hit as CWD != sandbox root.
    #
    # We fix this by monkeypatching pydevd (the library powering debugpy) so that a remoteRoot of "."
    # means the sandbox root.
    # See https://github.com/fabioz/PyDev.Debugger/pull/243 for a better solution.
    extra_env["PANTS_CHROOT"] = _in_chroot("").rstrip("/") if run_in_sandbox else "."
    args = [
        *regular_run_request.args,
        _in_chroot("__debugpy_launcher.py"),
        *debugpy.get_args(debug_adapter),
    ]

    return RunDebugAdapterRequest(
        digest=merged_digest,
        args=args,
        extra_env=extra_env,
        append_only_caches=regular_run_request.append_only_caches,
        immutable_input_digests=regular_run_request.immutable_input_digests,
    )
