# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from typing import cast

from pants.backend.nfpm.fields.all import NfpmDependencies
from pants.backend.nfpm.fields.contents import (
    NfpmContentDirDstField,
    NfpmContentDstField,
    NfpmContentFileSourceField,
    NfpmContentSrcField,
    NfpmContentSymlinkDstField,
)
from pants.backend.nfpm.field_sets import NFPM_PACKAGE_FIELD_SET_TYPES, NfpmPackageFieldSet
from pants.backend.nfpm.target_types import NfpmContentFile, NfpmPackageTarget
from pants.core.goals.package import PackageFieldSet, BuiltPackage, EnvironmentAwarePackageRequest
from pants.core.target_types import FileSourceField
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.engine.fs import CreateDigest, DigestEntries, FileEntry
from pants.engine.internals.native_engine import Digest, MergeDigests, Snapshot
from pants.engine.internals.selectors import Get, MultiGet
from pants.engine.rules import collect_rules, rule
from pants.engine.target import (
    DependenciesRequest,
    HydrateSourcesRequest,
    HydratedSources,
    SourcesField,
    Target,
    Targets,
    TransitiveTargets,
    FieldSetsPerTarget,
    FieldSetsPerTargetRequest,
    targets_with_sources_types,
)
from pants.engine.unions import UnionMembership


@dataclass(frozen=True)
class _NfpmSortedDeps:
    nfpm_content_from_dependency_targets: tuple[NfpmContentFile, ...]
    nfpm_content_from_source_targets: tuple[NfpmContentFile, ...]
    nfpm_package_targets: tuple[NfpmPackageTarget, ...]
    package_targets: tuple[Target, ...]
    remaining_targets: tuple[Target, ...]

    @classmethod
    def sort(
        cls,
        field_set: NfpmPackageFieldSet,
        transitive_targets: TransitiveTargets,
        union_membership: UnionMembership,
    ) -> _NfpmSortedDeps:
        package_field_set_types = (
            union_membership.get(PackageFieldSet) - NFPM_PACKAGE_FIELD_SET_TYPES
        )

        nfpm_content_from_dependency_targets: list[NfpmContentFile] = []
        nfpm_content_from_source_targets: list[NfpmContentFile] = []
        nfpm_package_targets: list[NfpmPackageTarget] = []
        package_targets: list[Target] = []
        remaining_targets: list[Target] = []

        # NB: TransitiveTargets is AFTER target generation/expansion (so there are no target generators)
        for tgt in transitive_targets.dependencies:
            if tgt.has_field(NfpmContentDirDstField) or tgt.has_field(NfpmContentSymlinkDstField):
                # NfpmContentDir and NfpmContentSymlink targets don't go in the sandbox.
                # They're only registered in the nfpm config.
                continue
            elif tgt.has_field(NfpmContentDstField):
                # an NfpmContentFile DOES need something in the sandbox

                # 'source' must be either None or a non-empty string.
                # If 'source' is None, the file comes from dependencies.
                if tgt[NfpmContentFileSourceField].value is None:
                    # The file must be hydrated from one of the dependencies.
                    nfpm_content_from_dependency_targets.append(cast(tgt, NfpmContentFile))
                    continue
                # The file must be hydrated from the 'source' field
                nfpm_content_from_source_targets.append(cast(tgt, NfpmContentFile))
                continue

            # This bool serves as a "continue" for the outer "for tgt" loop.
            identified_target = False

            for field_set_type in NFPM_PACKAGE_FIELD_SET_TYPES:
                if field_set_type.is_applicable(tgt):
                    identified_target = True
                    # we only respect nfpm package deps for the same packager
                    # (For example, deb targets will ignore any deps on rpm targets)
                    if isinstance(field_set, field_set_type):
                        nfpm_package_targets.append(cast(tgt, NfpmPackageTarget))
                    break
            if identified_target:
                continue

            for field_set_type in package_field_set_types:
                if field_set_type.is_applicable(tgt):
                    identified_target = True
                    package_targets.append(tgt)
                    break
            if identified_target:
                continue

            remaining_targets.append(tgt)

        return cls(
            nfpm_content_from_dependency_targets=tuple(nfpm_content_from_dependency_targets),
            nfpm_content_from_source_targets=tuple(nfpm_content_from_source_targets),
            nfpm_package_targets=tuple(nfpm_package_targets),
            package_targets=tuple(package_targets),
            remaining_targets=tuple(remaining_targets),
        )


@dataclass(frozen=True)
class NfpmPackagingSandboxRequest:
    field_set: NfpmPackageFieldSet
    transitive_targets: TransitiveTargets


@dataclass(frozen=True)
class NfpmPackagingSandbox:
    digest: Digest


@rule
async def populate_nfpm_packaging_sandbox(
    request: NfpmPackagingSandboxRequest, union_membership: UnionMembership
) -> NfpmPackagingSandbox:
    deps = _NfpmSortedDeps.sort(request.field_set, request.transitive_targets, union_membership)

    # Build packages for deps that are (non-nfpm) Packages
    package_field_sets_per_target = await Get(
        FieldSetsPerTarget, FieldSetsPerTargetRequest(PackageFieldSet, deps.package_targets)
    )
    packages = await MultiGet(
        Get(BuiltPackage, EnvironmentAwarePackageRequest(field_set))
        for field_set in package_field_sets_per_target.field_sets
    )

    # collect source fields to hydrate files.
    source_fields_to_relocate: list[tuple[SourcesField, NfpmContentSrcField]] = []
    source_fields: list[SourcesField] = []

    for nfpm_content_tgt in deps.nfpm_content_from_source_targets:
        source = nfpm_content_tgt.get(SourcesField)
        src = nfpm_content_tgt[NfpmContentSrcField]
        # If 'src' is empty, it defaults to the content target's 'source'.
        if src.value and source.value != src.value:
            source_fields_to_relocate.append((source, src))
        else:
            source_fields.append(source)

    source_from_dependency_targets = await MultiGet(
        Get(Targets, DependenciesRequest(tgt[NfpmDependencies]))
        for tgt in deps.nfpm_content_from_dependency_targets
    )
    file_tgts = (
        targets_with_sources_types([FileSourceField], tgts, union_membership)
        for tgts in source_from_dependency_targets
    )
    if any(not files for files in file_tgts):
        raise ValueError("One of the targets does not have a file target dependency")

    for files, nfpm_content_tgt in zip(file_tgts, deps.nfpm_content_from_dependency_targets):
        # we just grab the first one (as documented on the source and src fields)
        dep_tgt: Target = files[0]
        source = dep_tgt.get(SourcesField)
        src = nfpm_content_tgt[NfpmContentSrcField]
        # If 'src' is empty, it defaults to the dependency target's 'source'.
        if src.value and source.value != src.value:
            source_fields_to_relocate.append((source, src))
        else:
            source_fields.append(source)

    # Relocate sources
    # TODO: enable_codegen=True but for all possible codegen types?
    hydrated_sources_to_relocate = await MultiGet(
        Get(
            HydratedSources,
            HydrateSourcesRequest(field, for_sources_types=[FileSourceField], enable_codegen=True),
        )
        for field, _ in source_fields_to_relocate
    )
    relocated_source_entries = await MultiGet(
        Get(DigestEntries, Snapshot, hydrated.snapshot) for hydrated in hydrated_sources_to_relocate
    )
    moved_entries = []
    digest_entries: DigestEntries
    for digest_entries, (source, src) in zip(relocated_source_entries, source_fields_to_relocate):
        for entry in digest_entries:
            if isinstance(entry, FileEntry) and entry.path == source.value:
                moved_entries.append(dataclasses.replace(entry, path=src.alue))
            else:
                moved_entries.append(entry)

    # Hydrate sources
    relocated_sources_digest, sources = await MultiGet(
        Get(Digest, CreateDigest(moved_entries)),
        # TODO: enable_codegen=True but for all possible codegen types?
        Get(
            SourceFiles,
            SourceFilesRequest(
                source_fields, for_sources_types=[FileSourceField], enable_codegen=True
            ),
        ),
    )

    sandbox_digest = await Get(
        Digest,
        MergeDigests(
            [
                *(package.digest for package in packages),
                relocated_sources_digest,
                sources.snapshot.digest,
            ]
        ),
    )

    return NfpmPackagingSandbox(sandbox_digest)


def rules():
    return [*collect_rules()]
