# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os

from pants.backend.python.goals.package_pex_binary import PexBinaryFieldSet
from pants.backend.python.target_types import (
    PexBinaryDefaults,
    ResolvedPexEntryPoint,
    ResolvePexEntryPointRequest,
)
from pants.backend.python.util_rules.pex import Pex, PexRequest
from pants.backend.python.util_rules.pex_environment import WorkspacePexEnvironment
from pants.backend.python.util_rules.pex_from_targets import PexFromTargetsRequest
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
    field_set: PexBinaryFieldSet,
    pex_binary_defaults: PexBinaryDefaults,
    pex_env: WorkspacePexEnvironment,
) -> RunRequest:
    entry_point, transitive_targets = await MultiGet(
        Get(
            ResolvedPexEntryPoint,
            ResolvePexEntryPointRequest(field_set.entry_point),
        ),
        Get(TransitiveTargets, TransitiveTargetsRequest([field_set.address])),
    )

    # Note that we get an intermediate PexRequest here (instead of going straight to a Pex)
    # so that we can get the interpreter constraints for use in runner_pex_request.
    requirements_pex_request = await Get(
        PexRequest,
        PexFromTargetsRequest,
        PexFromTargetsRequest.for_requirements([field_set.address], internal_only=True),
    )

    requirements_request = Get(Pex, PexRequest, requirements_pex_request)

    sources_request = Get(
        PythonSourceFiles, PythonSourceFilesRequest(transitive_targets.closure, include_files=True)
    )

    output_filename = f"{field_set.address.target_name}.pex"
    runner_pex_request = Get(
        Pex,
        PexRequest(
            output_filename=output_filename,
            interpreter_constraints=requirements_pex_request.interpreter_constraints,
            additional_args=(
                *field_set.generate_additional_args(pex_binary_defaults),
                # N.B.: Since we cobble together the runtime environment via PEX_PATH and
                # PEX_EXTRA_SYS_PATH below, it's important for any app that re-executes itself that
                # these environment variables are not stripped.
                "--no-strip-pex-env",
            ),
            internal_only=True,
            # Note that the entry point file is not in the PEX itself. It's loaded by setting
            # `PEX_EXTRA_SYS_PATH`.
            # TODO(John Sirois): Support ConsoleScript in PexBinary targets:
            #  https://github.com/pantsbuild/pants/issues/11619
            main=entry_point.val,
        ),
    )

    requirements, sources, runner_pex = await MultiGet(
        requirements_request, sources_request, runner_pex_request
    )

    merged_digest = await Get(
        Digest,
        MergeDigests(
            [requirements.digest, sources.source_files.snapshot.digest, runner_pex.digest]
        ),
    )

    def in_chroot(relpath: str) -> str:
        return os.path.join("{chroot}", relpath)

    args = pex_env.create_argv(in_chroot(runner_pex.name), python=runner_pex.python)

    chrooted_source_roots = [in_chroot(sr) for sr in sources.source_roots]
    extra_env = {
        **pex_env.environment_dict(python_configured=runner_pex.python is not None),
        "PEX_PATH": in_chroot(requirements_pex_request.output_filename),
        "PEX_EXTRA_SYS_PATH": ":".join(chrooted_source_roots),
    }

    return RunRequest(digest=merged_digest, args=args, extra_env=extra_env)


def rules():
    return [*collect_rules(), UnionRule(RunFieldSet, PexBinaryFieldSet)]
