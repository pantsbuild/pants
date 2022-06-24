# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).


import dataclasses
import logging
import os

from pants.backend.python.goals.package_pex_binary import PexBinaryFieldSet
from pants.backend.python.subsystems.debugpy import DebugPy
from pants.backend.python.target_types import (
    PexBinaryDefaults,
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
from pants.core.goals.run import RunDebugAdapterRequest, RunFieldSet, RunRequest
from pants.engine.fs import Digest, MergeDigests
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import TransitiveTargets, TransitiveTargetsRequest
from pants.engine.unions import UnionRule
from pants.util.logging import LogLevel
from pants.util.strutil import softwrap

logger = logging.getLogger(__name__)


def _in_chroot(relpath: str) -> str:
    return os.path.join("{chroot}", relpath)


@rule(level=LogLevel.DEBUG)
async def create_pex_binary_run_request(
    field_set: PexBinaryFieldSet, pex_binary_defaults: PexBinaryDefaults, pex_env: PexEnvironment
) -> RunRequest:
    run_in_sandbox = field_set.run_in_sandbox.value
    entry_point, transitive_targets = await MultiGet(
        Get(
            ResolvedPexEntryPoint,
            ResolvePexEntryPointRequest(field_set.entry_point),
        ),
        Get(TransitiveTargets, TransitiveTargetsRequest([field_set.address])),
    )

    addresses = [field_set.address]
    interpreter_constraints = await Get(
        InterpreterConstraints, InterpreterConstraintsRequest(addresses)
    )

    pex_filename = (
        field_set.address.generated_name.replace(".", "_")
        if field_set.address.generated_name
        else field_set.address.target_name
    )
    pex_get = Get(
        Pex,
        PexFromTargetsRequest(
            [field_set.address],
            output_filename=f"{pex_filename}.pex",
            internal_only=True,
            include_source_files=False,
            # Note that the file for first-party entry points is not in the PEX itself. In that
            # case, it's loaded by setting `PEX_EXTRA_SYS_PATH`.
            main=entry_point.val or field_set.script.value,
            additional_args=(
                *field_set.generate_additional_args(pex_binary_defaults),
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
            [field_set.address],
            internal_only=True,
            interpreter_constraints=interpreter_constraints,
            sources=sources,
        ),
    )

    input_digests = [
        pex.digest,
        local_dists.pex.digest,
        # Note regarding inline mode: You might think that the sources don't need to be copied
        # into the chroot when using inline sources. But they do, because some of them might be
        # codegenned, and those won't exist in the inline source tree. Rather than incurring the
        # complexity of figuring out here which sources were codegenned, we copy everything.
        # The inline source roots precede the chrooted ones in PEX_EXTRA_SYS_PATH, so the inline
        # sources will take precedence and their copies in the chroot will be ignored.
        local_dists.remaining_sources.source_files.snapshot.digest,
    ]
    merged_digest = await Get(Digest, MergeDigests(input_digests))

    complete_pex_env = pex_env.in_workspace()
    # NB. If this changes, please consider how it affects the `DebugRequest` below
    # (which is not easy to write automated tests for)
    args = complete_pex_env.create_argv(_in_chroot(pex.name), python=pex.python)

    chrooted_source_roots = [_in_chroot(sr) for sr in sources.source_roots]
    # The order here is important: we want the in-repo sources to take precedence over their
    # copies in the sandbox (see above for why those copies exist even in non-sandboxed mode).
    source_roots = [
        *([] if run_in_sandbox else sources.source_roots),
        *chrooted_source_roots,
    ]
    extra_env = {
        **complete_pex_env.environment_dict(python_configured=pex.python is not None),
        "PEX_PATH": _in_chroot(local_dists.pex.name),
        "PEX_EXTRA_SYS_PATH": os.pathsep.join(source_roots),
    }

    return RunRequest(digest=merged_digest, args=args, extra_env=extra_env)


@rule
async def run_pex_debug_adapter_binary(
    field_set: PexBinaryFieldSet,
    debugpy: DebugPy,
) -> RunDebugAdapterRequest:
    if field_set.run_in_sandbox:
        logger.warning(
            softwrap(
                """
                Using --debug-adapter with `run_in_sandbox` set to `True` will likely cause your
                breakpoints to not be hit, as your code will be run under the sandbox's path.
                """
            )
        )

    debugpy_pex_request = debugpy.to_pex_request()
    debugpy_pex_request = dataclasses.replace(
        debugpy_pex_request,
        additional_args=debugpy_pex_request.additional_args + ("--no-strip-pex-env",),
    )

    entry_point, regular_run_request, debugpy_pex = await MultiGet(
        Get(
            ResolvedPexEntryPoint,
            ResolvePexEntryPointRequest(field_set.entry_point),
        ),
        Get(RunRequest, PexBinaryFieldSet, field_set),
        Get(Pex, PexRequest, debugpy_pex_request),
    )

    entry_point_or_script = entry_point.val or field_set.script.value
    assert entry_point_or_script is not None
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
    args = [
        regular_run_request.args[0],  # python executable
        _in_chroot(debugpy_pex.name),
        "--listen",
        f"{debugpy.host}:{debugpy.port}",
        "--wait-for-client",
        *debugpy.main_spec_args(entry_point_or_script),
    ]

    return RunDebugAdapterRequest(digest=merged_digest, args=args, extra_env=extra_env)


def rules():
    return [*collect_rules(), UnionRule(RunFieldSet, PexBinaryFieldSet)]
