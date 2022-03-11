# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os

from pants.backend.python.goals.package_pex_binary import PexBinaryFieldSet
from pants.backend.python.target_types import (
    PexBinaryDefaults,
    ResolvedPexEntryPoint,
    ResolvePexEntryPointRequest,
)
from pants.backend.python.util_rules.interpreter_constraints import InterpreterConstraints
from pants.backend.python.util_rules.local_dists import LocalDistsPex, LocalDistsPexRequest
from pants.backend.python.util_rules.pex import Pex
from pants.backend.python.util_rules.pex_environment import PexEnvironment
from pants.backend.python.util_rules.pex_from_targets import (
    InterpreterConstraintsRequest,
    PexFromTargetsRequest,
)
from pants.backend.python.util_rules.python_sources import (
    PythonSourceFiles,
    PythonSourceFilesRequest,
)
from pants.core.goals.run import RunFieldSet, RunRequest
from pants.engine.fs import Digest, MergeDigests
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import TransitiveTargets, TransitiveTargetsRequest
from pants.engine.unions import UnionRule
from pants.util.logging import LogLevel


@rule(level=LogLevel.DEBUG)
async def create_pex_binary_run_request(
    field_set: PexBinaryFieldSet, pex_binary_defaults: PexBinaryDefaults, pex_env: PexEnvironment
) -> RunRequest:
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

    merged_digest = await Get(
        Digest,
        MergeDigests(
            [
                pex.digest,
                local_dists.pex.digest,
                local_dists.remaining_sources.source_files.snapshot.digest,
            ]
        ),
    )

    def in_chroot(relpath: str) -> str:
        return os.path.join("{chroot}", relpath)

    complete_pex_env = pex_env.in_workspace()
    args = complete_pex_env.create_argv(in_chroot(pex.name), python=pex.python)

    chrooted_source_roots = [in_chroot(sr) for sr in sources.source_roots]
    extra_env = {
        **complete_pex_env.environment_dict(python_configured=pex.python is not None),
        "PEX_PATH": in_chroot(local_dists.pex.name),
        "PEX_EXTRA_SYS_PATH": os.pathsep.join(chrooted_source_roots),
    }

    return RunRequest(digest=merged_digest, args=args, extra_env=extra_env)


def rules():
    return [*collect_rules(), UnionRule(RunFieldSet, PexBinaryFieldSet)]
