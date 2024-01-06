# Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
import itertools
import logging
from dataclasses import dataclass
from pathlib import PurePath

from pants.backend.makeself.goals.run import MakeselfArchiveFieldSet
from pants.backend.makeself.makeself import CreateMakeselfArchive
from pants.backend.shell.target_types import ShellSourceField
from pants.core.goals import package
from pants.core.goals.package import (
    BuiltPackage,
    BuiltPackageArtifact,
    EnvironmentAwarePackageRequest,
    PackageFieldSet,
)
from pants.core.target_types import FileSourceField
from pants.core.util_rules import source_files
from pants.engine.addresses import UnparsedAddressInputs
from pants.engine.fs import Digest, MergeDigests
from pants.engine.internals.native_engine import AddPrefix, Snapshot
from pants.engine.process import ProcessResult
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import (
    FieldSetsPerTarget,
    FieldSetsPerTargetRequest,
    HydratedSources,
    HydrateSourcesRequest,
    SourcesField,
    Targets,
)
from pants.engine.unions import UnionRule
from pants.util.logging import LogLevel

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class BuiltMakeselfArchiveArtifact(BuiltPackageArtifact):
    @classmethod
    def create(cls, relpath: str) -> "BuiltMakeselfArchiveArtifact":
        return cls(
            relpath=relpath,
            extra_log_lines=(f"Built Makeself binary: {relpath}",),
        )


@rule
async def package_makeself_binary(field_set: MakeselfArchiveFieldSet) -> BuiltPackage:
    archive_dir = "__archive"

    startup_script_targets, package_targets, file_targets = await MultiGet(
        Get(Targets, UnparsedAddressInputs, field_set.startup_script.to_unparsed_address_inputs()),
        Get(Targets, UnparsedAddressInputs, field_set.packages.to_unparsed_address_inputs()),
        Get(Targets, UnparsedAddressInputs, field_set.files.to_unparsed_address_inputs()),
    )

    package_field_sets_per_target = await Get(
        FieldSetsPerTarget, FieldSetsPerTargetRequest(PackageFieldSet, package_targets)
    )
    packages = await MultiGet(
        Get(BuiltPackage, EnvironmentAwarePackageRequest(field_set))
        for field_set in package_field_sets_per_target.field_sets
    )

    startup_script, *file_sources = await MultiGet(
        Get(
            HydratedSources,
            HydrateSourcesRequest(
                tgt.get(SourcesField),
                for_sources_types=(FileSourceField, ShellSourceField),
                enable_codegen=True,
            ),
        )
        for tgt in itertools.chain(startup_script_targets, file_targets)
    )

    assert len(startup_script.snapshot.files) == 1, (startup_script, file_sources)

    input_digest = await Get(
        Digest,
        MergeDigests(
            (
                startup_script.snapshot.digest,
                *(package.digest for package in packages),
                *(sources.snapshot.digest for sources in file_sources),
            )
        ),
    )
    input_digest = await Get(Digest, AddPrefix(input_digest, archive_dir))

    output_path = PurePath(field_set.output_path.value_or_default(file_ending="run"))
    output_filename = output_path.name
    startup_script_file = startup_script.snapshot.files[0]
    result = await Get(
        ProcessResult,
        CreateMakeselfArchive(
            archive_dir=archive_dir,
            file_name=output_filename,
            label=field_set.label.value or output_filename,
            startup_script=startup_script_file,
            input_digest=input_digest,
            output_filename=output_filename,
            description=f"Packaging makeself archive: {field_set.address}",
            level=LogLevel.DEBUG,
        ),
    )
    digest = await Get(Digest, AddPrefix(result.output_digest, str(output_path.parent)))
    snapshot = await Get(Snapshot, Digest, digest)
    assert len(snapshot.files) == 1, snapshot

    return BuiltPackage(
        snapshot.digest,
        artifacts=tuple(BuiltMakeselfArchiveArtifact.create(file) for file in snapshot.files),
    )


def rules():
    return [
        *collect_rules(),
        *package.rules(),
        *source_files.rules(),
        *MakeselfArchiveFieldSet.rules(),
        UnionRule(PackageFieldSet, MakeselfArchiveFieldSet),
    ]
