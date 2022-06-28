# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import os
from typing import Iterable, Optional

from pants.backend.python.subsystems.debugpy import DebugPy
from pants.backend.python.target_types import (
    ConsoleScript,
    PexEntryPointField,
    ResolvedPexEntryPoint,
    ResolvePexEntryPointRequest,
)
from pants.backend.python.util_rules.interpreter_constraints import InterpreterConstraints
from pants.backend.python.util_rules.local_dists import LocalDistsPex, LocalDistsPexRequest
from pants.backend.python.util_rules.pex import Pex, PexRequest
from pants.backend.python.util_rules.pex_environment import PexEnvironment
from pants.backend.python.util_rules.pex_from_targets import (
    InterpreterConstraintsRequest,
    PexFromTargetsRequest,
)
from pants.backend.python.util_rules.python_sources import (
    PythonSourceFiles,
    PythonSourceFilesRequest,
)
from pants.core.goals.run import RunDebugAdapterRequest, RunRequest
from pants.core.subsystems.debug_adapter import DebugAdapterSubsystem
from pants.engine.addresses import Address
from pants.engine.fs import Digest, MergeDigests
from pants.engine.rules import Get, MultiGet, rule_helper
from pants.engine.target import TransitiveTargets, TransitiveTargetsRequest


def _in_chroot(relpath: str) -> str:
    return os.path.join("{chroot}", relpath)


@rule_helper
async def _create_python_source_run_request(
    address: Address,
    *,
    entry_point_field: PexEntryPointField,
    pex_env: PexEnvironment,
    run_in_sandbox: bool,
    console_script: Optional[ConsoleScript] = None,
    additional_pex_args: Iterable[str] = (),
) -> RunRequest:
    addresses = [address]
    entry_point, transitive_targets = await MultiGet(
        Get(
            ResolvedPexEntryPoint,
            ResolvePexEntryPointRequest(entry_point_field),
        ),
        Get(TransitiveTargets, TransitiveTargetsRequest(addresses)),
    )

    interpreter_constraints = await Get(
        InterpreterConstraints, InterpreterConstraintsRequest(addresses)
    )

    pex_filename = (
        address.generated_name.replace(".", "_") if address.generated_name else address.target_name
    )
    pex_get = Get(
        Pex,
        PexFromTargetsRequest(
            addresses,
            output_filename=f"{pex_filename}.pex",
            internal_only=True,
            include_source_files=False,
            # `PEX_EXTRA_SYS_PATH` should contain this entry_point's module.
            main=console_script or entry_point.val,
            additional_args=(
                *additional_pex_args,
                # N.B.: Since we cobble together the runtime environment via PEX_EXTRA_SYS_PATH
                # below, it's important for any app that re-executes itself that these environment
                # variables are not stripped.
                "--no-strip-pex-env",
            ),
        ),
    )
    sources_get = Get(
        PythonSourceFiles, PythonSourceFilesRequest(transitive_targets.closure, include_files=True)
    )
    pex, sources = await MultiGet(pex_get, sources_get)

    local_dists = await Get(
        LocalDistsPex,
        LocalDistsPexRequest(
            addresses,
            internal_only=True,
            interpreter_constraints=interpreter_constraints,
            sources=sources,
        ),
    )

    input_digests = [
        pex.digest,
        local_dists.pex.digest,
        # Note regarding not-in-sandbox mode: You might think that the sources don't need to be copied
        # into the chroot when using inline sources. But they do, because some of them might be
        # codegenned, and those won't exist in the inline source tree. Rather than incurring the
        # complexity of figuring out here which sources were codegenned, we copy everything.
        # The inline source roots precede the chrooted ones in PEX_EXTRA_SYS_PATH, so the inline
        # sources will take precedence and their copies in the chroot will be ignored.
        local_dists.remaining_sources.source_files.snapshot.digest,
    ]
    merged_digest = await Get(Digest, MergeDigests(input_digests))

    complete_pex_env = pex_env.in_workspace()
    args = complete_pex_env.create_argv(_in_chroot(pex.name), python=pex.python)

    chrooted_source_roots = [_in_chroot(sr) for sr in sources.source_roots]
    # The order here is important: we want the in-repo sources to take precedence over their
    # copies in the sandbox (see above for why those copies exist even in non-sandboxed mode).
    source_roots = [
        *([] if run_in_sandbox else sources.source_roots),
        *chrooted_source_roots,
    ]
    extra_env = {
        **pex_env.in_workspace().environment_dict(python_configured=pex.python is not None),
        "PEX_PATH": _in_chroot(local_dists.pex.name),
        "PEX_EXTRA_SYS_PATH": os.pathsep.join(source_roots),
    }

    return RunRequest(
        digest=merged_digest,
        args=args,
        extra_env=extra_env,
    )


@rule_helper
async def _create_python_source_run_dap_request(
    regular_run_request: RunRequest,
    *,
    entry_point_field: PexEntryPointField,
    debugpy: DebugPy,
    debug_adapter: DebugAdapterSubsystem,
    console_script: Optional[ConsoleScript] = None,
) -> RunDebugAdapterRequest:
    entry_point, debugpy_pex = await MultiGet(
        Get(
            ResolvedPexEntryPoint,
            ResolvePexEntryPointRequest(entry_point_field),
        ),
        Get(Pex, PexRequest, debugpy.to_pex_request()),
    )

    merged_digest = await Get(
        Digest, MergeDigests([regular_run_request.digest, debugpy_pex.digest])
    )
    extra_env = dict(regular_run_request.extra_env)
    extra_env["PEX_PATH"] = os.pathsep.join(
        [
            extra_env["PEX_PATH"],
            # For debugpy to work properly, we need to have just one "environment" for our
            # command to run in. Therefore, we cobble one together by exeucting debugpy's PEX, and
            # shoehorning in the original PEX through PEX_PATH.
            _in_chroot(os.path.basename(regular_run_request.args[1])),
        ]
    )
    main = console_script or entry_point.val
    assert main is not None
    args = [
        regular_run_request.args[0],  # python executable
        _in_chroot(debugpy_pex.name),
        *debugpy.get_args(debug_adapter, main),
    ]

    return RunDebugAdapterRequest(digest=merged_digest, args=args, extra_env=extra_env)
