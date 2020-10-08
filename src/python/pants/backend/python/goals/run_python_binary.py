# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os

from pants.backend.python.goals.package_python_binary import PythonBinaryFieldSet
from pants.backend.python.target_types import PythonBinaryDefaults, PythonBinarySources
from pants.backend.python.util_rules.pex import Pex, PexRequest
from pants.backend.python.util_rules.pex_environment import PexEnvironment
from pants.backend.python.util_rules.pex_from_targets import PexFromTargetsRequest
from pants.backend.python.util_rules.python_sources import (
    PythonSourceFiles,
    PythonSourceFilesRequest,
)
from pants.core.goals.run import RunFieldSet, RunRequest
from pants.engine.fs import Digest, MergeDigests, PathGlobs, Paths
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import InvalidFieldException, TransitiveTargets, TransitiveTargetsRequest
from pants.engine.unions import UnionRule
from pants.option.global_options import FilesNotFoundBehavior
from pants.source.source_root import SourceRoot, SourceRootRequest
from pants.util.logging import LogLevel


@rule(level=LogLevel.DEBUG)
async def create_python_binary_run_request(
    field_set: PythonBinaryFieldSet,
    python_binary_defaults: PythonBinaryDefaults,
    pex_env: PexEnvironment,
) -> RunRequest:
    entry_point = field_set.entry_point.value
    if entry_point is None:
        binary_source_paths = await Get(
            Paths, PathGlobs, field_set.sources.path_globs(FilesNotFoundBehavior.error)
        )
        if len(binary_source_paths.files) != 1:
            raise InvalidFieldException(
                "No `entry_point` was set for the target "
                f"{repr(field_set.address)}, so it must have exactly one source, but it has "
                f"{len(binary_source_paths.files)}"
            )
        entry_point_path = binary_source_paths.files[0]
        source_root = await Get(
            SourceRoot,
            SourceRootRequest,
            SourceRootRequest.for_file(entry_point_path),
        )
        entry_point = PythonBinarySources.translate_source_file_to_entry_point(
            os.path.relpath(entry_point_path, source_root.path)
        )
    transitive_targets = await Get(TransitiveTargets, TransitiveTargetsRequest([field_set.address]))

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
            additional_args=field_set.generate_additional_args(python_binary_defaults),
            internal_only=True,
            # Note that the entry point file is not in the Pex itself, but on the
            # PEX_PATH. This works fine!
            entry_point=entry_point,
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
    return [*collect_rules(), UnionRule(RunFieldSet, PythonBinaryFieldSet)]
