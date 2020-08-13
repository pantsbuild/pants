# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os

from pants.backend.python.rules.create_python_binary import PythonBinaryFieldSet
from pants.backend.python.rules.pex import Pex, PexPlatforms
from pants.backend.python.rules.pex_from_targets import PexFromTargetsRequest
from pants.backend.python.rules.python_sources import PythonSourceFiles, PythonSourceFilesRequest
from pants.backend.python.target_types import PythonBinaryDefaults, PythonBinarySources
from pants.core.goals.binary import BinaryFieldSet
from pants.core.goals.run import RunRequest
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


@rule
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

    output_filename = f"{field_set.address.target_name}.pex"
    pex_request = Get(
        Pex,
        PexFromTargetsRequest(
            addresses=Addresses([field_set.address]),
            platforms=PexPlatforms.create_from_platforms_field(field_set.platforms),
            output_filename=output_filename,
            additional_args=field_set.generate_additional_args(python_binary_defaults),
            include_source_files=False,
        ),
    )
    sources_request = Get(
        PythonSourceFiles, PythonSourceFilesRequest(transitive_targets.closure, include_files=True),
    )
    pex, sources = await MultiGet(pex_request, sources_request)

    merged_digest = await Get(
        Digest, MergeDigests([pex.digest, sources.source_files.snapshot.digest])
    )
    chrooted_source_roots = [os.path.join("{chroot}", sr) for sr in sources.source_roots]
    return RunRequest(
        digest=merged_digest,
        args=(os.path.join("{chroot}", pex.output_filename), "-m", entry_point),
        env={"PEX_EXTRA_SYS_PATH": ":".join(chrooted_source_roots)},
    )


def rules():
    return [
        *collect_rules(),
        UnionRule(BinaryFieldSet, PythonBinaryFieldSet),
    ]
