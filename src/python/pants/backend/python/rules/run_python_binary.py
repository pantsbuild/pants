# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os

from pants.backend.python.rules.create_python_binary import PythonBinaryFieldSet
from pants.backend.python.rules.pex import Pex, PexRequest
from pants.backend.python.rules.pex_from_targets import PexFromTargetsRequest
from pants.backend.python.rules.python_sources import PythonSourceFiles, PythonSourceFilesRequest
from pants.backend.python.target_types import PythonBinaryDefaults, PythonBinarySources
from pants.core.goals.run import RunFieldSet, RunRequest
from pants.core.util_rules.source_files import SourceFiles
from pants.core.util_rules.stripped_source_files import StrippedSourceFiles
from pants.engine.addresses import Addresses
from pants.engine.fs import Digest, MergeDigests
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import (
    HydratedSources,
    HydrateSourcesRequest,
    InvalidFieldException,
    TransitiveTargets,
)
from pants.engine.unions import UnionRule
from pants.util.logging import LogLevel


@rule(level=LogLevel.DEBUG)
async def create_python_binary_run_request(
    field_set: PythonBinaryFieldSet, python_binary_defaults: PythonBinaryDefaults
) -> RunRequest:
    entry_point = field_set.entry_point.value
    if entry_point is None:
        # TODO: This is overkill? We don't need to hydrate the sources and strip snapshots,
        #  we only need the path relative to the source root.
        binary_sources = await Get(HydratedSources, HydrateSourcesRequest(field_set.sources))
        stripped_binary_sources = await Get(
            StrippedSourceFiles, SourceFiles(binary_sources.snapshot, ())
        )
        entry_point = PythonBinarySources.translate_source_file_to_entry_point(
            stripped_binary_sources.snapshot.files
        )
    if entry_point is None:
        raise InvalidFieldException(
            "You must either specify `sources` or `entry_point` for the target "
            f"{repr(field_set.address)} in order to run it, but both fields were undefined."
        )

    transitive_targets = await Get(TransitiveTargets, Addresses([field_set.address]))

    # Note that we get an intermediate PexRequest here (instead of going straight to a Pex)
    # so that we can get the interpreter constraints for use in runner_pex_request.
    requirements_pex_request = await Get(
        PexRequest,
        PexFromTargetsRequest,
        PexFromTargetsRequest.for_requirements(Addresses([field_set.address]), internal_only=True),
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

    chrooted_source_roots = [in_chroot(sr) for sr in sources.source_roots]
    pex_path = in_chroot(requirements_pex_request.output_filename)
    return RunRequest(
        digest=merged_digest,
        args=(in_chroot(runner_pex.name), "-m", entry_point),
        env={"PEX_PATH": pex_path, "PEX_EXTRA_SYS_PATH": ":".join(chrooted_source_roots)},
    )


def rules():
    return [
        *collect_rules(),
        UnionRule(RunFieldSet, PythonBinaryFieldSet),
    ]
