# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.python.rules.create_python_binary import PythonBinaryFieldSet
from pants.backend.python.rules.pex import Pex, PexPlatforms
from pants.backend.python.rules.pex_from_targets import PexFromTargetsRequest
from pants.backend.python.rules.python_sources import (
    UnstrippedPythonSources,
    UnstrippedPythonSourcesRequest,
)
from pants.backend.python.target_types import PythonBinaryDefaults, PythonBinarySources
from pants.core.goals.binary import BinaryFieldSet
from pants.core.goals.run import RunRequest
from pants.core.util_rules.determine_source_files import AllSourceFilesRequest, SourceFiles
from pants.engine.addresses import Addresses
from pants.engine.fs import Digest, MergeDigests
from pants.engine.rules import SubsystemRule, rule
from pants.engine.selectors import Get, MultiGet
from pants.engine.target import InvalidFieldException, TransitiveTargets
from pants.engine.unions import UnionRule


@rule
async def create_python_binary_run_request(
    field_set: PythonBinaryFieldSet, python_binary_defaults: PythonBinaryDefaults
) -> RunRequest:
    entry_point = field_set.entry_point.value
    if entry_point is None:
        binary_sources = await Get(
            SourceFiles, AllSourceFilesRequest([field_set.sources], strip_source_roots=True)
        )
        entry_point = PythonBinarySources.translate_source_file_to_entry_point(binary_sources.files)
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
            distributed_to_users=False,
            platforms=PexPlatforms.create_from_platforms_field(field_set.platforms),
            output_filename=output_filename,
            additional_args=field_set.generate_additional_args(python_binary_defaults),
            include_source_files=False,
        ),
    )
    source_files_request = Get(
        UnstrippedPythonSources,
        UnstrippedPythonSourcesRequest(transitive_targets.closure, include_files=True),
    )
    pex, source_files = await MultiGet(pex_request, source_files_request)

    merged_digest = await Get(Digest, MergeDigests([pex.digest, source_files.snapshot.digest]))
    return RunRequest(
        digest=merged_digest,
        binary_name=pex.output_filename,
        prefix_args=("-m", entry_point),
        env={"PEX_EXTRA_SYS_PATH": ":".join(source_files.source_roots)},
    )


def rules():
    return [
        create_python_binary_run_request,
        UnionRule(BinaryFieldSet, PythonBinaryFieldSet),
        SubsystemRule(PythonBinaryDefaults),
    ]
