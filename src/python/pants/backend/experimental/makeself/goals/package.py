import logging
from dataclasses import dataclass
from pathlib import PurePath

from pants.core.goals import package
from pants.core.goals.package import (
    BuiltPackage,
    BuiltPackageArtifact,
    EnvironmentAwarePackageRequest,
    OutputPathField,
    PackageFieldSet,
)
from pants.core.goals.run import RunFieldSet, RunInSandboxBehavior
from pants.core.target_types import FileSourceField
from pants.core.util_rules import source_files
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
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
from pants_backend_makeself.makeself import CreateMakeselfArchive
from pants_backend_makeself.target_types import (
    MakeselfArchiveFilesField,
    MakeselfArchivePackagesField,
    MakeselfArchiveStartupScript,
    MakeselfArthiveLabel,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class BuiltMakeselfArchiveArtifact(BuiltPackageArtifact):
    @classmethod
    def create(cls, relpath: str) -> "BuiltMakeselfArchiveArtifact":
        return cls(
            relpath=relpath,
            extra_log_lines=(f"Built Makeself binary: {relpath}",),
        )


@dataclass(frozen=True)
class MakeselfArchiveFieldSet(PackageFieldSet, RunFieldSet):
    required_fields = (MakeselfArchiveStartupScript,)
    run_in_sandbox_behavior = RunInSandboxBehavior.RUN_REQUEST_HERMETIC

    startup_script: MakeselfArchiveStartupScript
    label: MakeselfArthiveLabel
    files: MakeselfArchiveFilesField
    packages: MakeselfArchivePackagesField
    output_path: OutputPathField


@rule
async def package_makeself_binary(
    field_set: MakeselfArchiveFieldSet,
) -> BuiltPackage:
    archive_dir = "__archive"

    package_targets, file_targets = await MultiGet(
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

    file_sources = await MultiGet(
        Get(
            HydratedSources,
            HydrateSourcesRequest(
                tgt.get(SourcesField),
                for_sources_types=(FileSourceField,),
                enable_codegen=True,
            ),
        )
        for tgt in file_targets
    )

    startup_script = await Get(SourceFiles, SourceFilesRequest([field_set.startup_script]))
    assert len(startup_script.files) == 1, startup_script.files

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
    startup_script_filename = startup_script.files[0]
    result = await Get(
        ProcessResult,
        CreateMakeselfArchive(
            archive_dir=archive_dir,
            file_name=output_filename,
            label=field_set.label.value or output_filename,
            startup_script=startup_script_filename,
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
