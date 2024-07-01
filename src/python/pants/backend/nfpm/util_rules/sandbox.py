# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from enum import Enum, auto
from typing import Type, cast

from pants.backend.nfpm.field_sets import NFPM_PACKAGE_FIELD_SET_TYPES, NfpmPackageFieldSet
from pants.backend.nfpm.fields.contents import (
    NfpmContentDirDstField,
    NfpmContentDstField,
    NfpmContentFileSourceField,
    NfpmContentSrcField,
    NfpmContentSymlinkDstField,
)
from pants.backend.nfpm.target_types import NfpmContentFile, NfpmPackageTarget
from pants.core.goals.package import (
    BuiltPackage,
    EnvironmentAwarePackageRequest,
    PackageFieldSet,
    TraverseIfNotPackageTarget,
)
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.engine.fs import CreateDigest, DigestEntries, Directory, FileEntry, SymlinkEntry
from pants.engine.internals.native_engine import Digest, MergeDigests, Snapshot
from pants.engine.internals.selectors import Get, MultiGet
from pants.engine.rules import collect_rules, rule
from pants.engine.target import (
    FieldSetsPerTarget,
    FieldSetsPerTargetRequest,
    GenerateSourcesRequest,
    HydratedSources,
    HydrateSourcesRequest,
    SourcesField,
    Target,
    TransitiveTargets,
    TransitiveTargetsRequest,
)
from pants.engine.unions import UnionMembership


class _DepCategory(Enum):
    ignore = auto()
    nfpm_content_from_dependency = auto()
    nfpm_content_from_source = auto()
    nfpm_package = auto()
    remaining = auto()

    @classmethod
    def for_target(
        cls,
        tgt: Target,
        field_set_type: Type[NfpmPackageFieldSet],
    ) -> _DepCategory:
        # Assumption: this gets called with atomic targets not target generators. For example,
        # TransitiveTargets gets calculated AFTER target generation/expansion.
        if tgt.has_field(NfpmContentDirDstField) or tgt.has_field(NfpmContentSymlinkDstField):
            # NfpmContentDir and NfpmContentSymlink targets don't go in the sandbox.
            # They're only registered in the nfpm config.
            return _depCategory.ignore
        if tgt.has_field(NfpmContentDstField):
            # an NfpmContentFile DOES need something in the sandbox

            # 'source' must be either None or a non-empty string.
            # If 'source' is None, the file comes from dependencies.
            if tgt[NfpmContentFileSourceField].value is None:
                # The file must be hydrated from one of the dependencies.
                return _depCategory.nfpm_content_from_dependency
            # The file must be hydrated from the 'source' field
            return _depCategory.nfpm_content_from_source

        for pkg_field_set_type in NFPM_PACKAGE_FIELD_SET_TYPES:
            if pkg_field_set_type.is_applicable(tgt):
                # we only respect nfpm package deps for the same packager
                # (For example, deb targets will ignore any deps on rpm targets)
                if pkg_field_set_type == field_set_type:
                    return _depCategory.nfpm_package
                return _depCategory.ignore

        return _depCategory.remaining


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

        for tgt in transitive_targets.dependencies:
            category = _DepCategory.for_target(tgt, type(field_set))
            if category == _DepCategory.ignore:
                continue
            elif category == _DepCategory.nfpm_content_from_dependency:
                nfpm_content_from_dependency_targets.append(cast(NfpmContentFile, tgt))
            elif category == _DepCategory.nfpm_content_from_source:
                nfpm_content_from_source_targets.append(cast(NfpmContentFile, tgt))
            elif category == _DepCategory.nfpm_package:
                nfpm_package_targets.append(cast(NfpmPackageTarget, tgt))
            elif category == _DepCategory.remaining:
                is_package = False
                for field_set_type in package_field_set_types:
                    if field_set_type.is_applicable(tgt):
                        is_package = True
                        package_targets.append(tgt)
                        break
                if not is_package:
                    remaining_targets.append(tgt)
            else:
                raise ValueError(f"Please file a bug report--got unknown _DepCategory: {category}")

        return cls(
            nfpm_content_from_dependency_targets=tuple(nfpm_content_from_dependency_targets),
            nfpm_content_from_source_targets=tuple(nfpm_content_from_source_targets),
            nfpm_package_targets=tuple(nfpm_package_targets),
            package_targets=tuple(package_targets),
            remaining_targets=tuple(remaining_targets),
        )


@dataclass(frozen=True)
class NfpmContentSandboxRequest:
    field_set: NfpmPackageFieldSet


@dataclass(frozen=True)
class NfpmContentSandbox:
    digest: Digest


@rule
async def populate_nfpm_content_sandbox(
    request: NfpmContentSandboxRequest, union_membership: UnionMembership
) -> NfpmContentSandbox:
    transitive_targets = await Get(
        TransitiveTargets,
        TransitiveTargetsRequest(
            [request.field_set.address],
            should_traverse_deps_predicate=TraverseIfNotPackageTarget(
                roots=[request.field_set.address],
                union_membership=union_membership,
            ),
        ),
    )

    deps = _NfpmSortedDeps.sort(request.field_set, transitive_targets, union_membership)

    # 1. Build packages for deps that are (non-nfpm) Packages

    package_field_sets_per_target = await Get(
        FieldSetsPerTarget, FieldSetsPerTargetRequest(PackageFieldSet, deps.package_targets)
    )
    packages = await MultiGet(
        Get(BuiltPackage, EnvironmentAwarePackageRequest(field_set))
        for field_set in package_field_sets_per_target.field_sets
    )

    # 2. Hydrate 'source' fields for nfpm_content_file targets.

    nfpm_content_source_fields_to_relocate: list[
        tuple[NfpmContentFileSourceField, NfpmContentSrcField]
    ] = []
    nfpm_content_source_fields: list[SourcesField] = []

    for nfpm_content_tgt in deps.nfpm_content_from_source_targets:
        source = nfpm_content_tgt[NfpmContentFileSourceField]
        src = nfpm_content_tgt[NfpmContentSrcField]
        # If 'src' is empty, it defaults to the content target's 'source'.
        if src.value and source.value != src.value:
            nfpm_content_source_fields_to_relocate.append((source, src))
        else:
            nfpm_content_source_fields.append(source)

    hydrated_sources_to_relocate = await MultiGet(
        Get(HydratedSources, HydrateSourcesRequest(field))
        for field, _ in nfpm_content_source_fields_to_relocate
    )
    relocated_source_entries = await MultiGet(
        Get(DigestEntries, Snapshot, hydrated.snapshot) for hydrated in hydrated_sources_to_relocate
    )
    moved_entries: list[FileEntry | SymlinkEntry | Directory] = []
    digest_entries: DigestEntries
    for digest_entries, (source, src) in zip(
        relocated_source_entries, nfpm_content_source_fields_to_relocate
    ):
        for entry in digest_entries:
            if isinstance(entry, FileEntry) and entry.path == source.value:
                moved_entries.append(dataclasses.replace(entry, path=src.value))
            else:
                moved_entries.append(entry)

    nfpm_content_relocated_sources_digest, nfpm_content_sources = await MultiGet(
        Get(Digest, CreateDigest(moved_entries)),
        # nfpm_content_file sources are simply files -- no codegen required.
        # anything more involved (like downloading http_source()) should use 'dependencies' instead
        # (for example, depend on a 'file(source=http_source(...))' target to download something).
        Get(SourceFiles, SourceFilesRequest(nfpm_content_source_fields)),
    )

    # 3. Hydrate sources from 'dependencies' fields for nfpm_content_file targets,
    # which should all be accounted for in the transitive targets in deps.remaining_targets.

    # This involves doing as much codegen as possible (based on export_codegen goal).
    codegen_inputs_to_outputs = [
        (req.input, req.output) for req in union_membership.get(GenerateSourcesRequest)
    ]
    codegen_sources_fields_with_output = []
    for tgt in deps.remaining_targets:
        if not tgt.has_field(SourcesField):
            continue
        sources_field = tgt[SourcesField]
        found = False
        for input_type, output_type in codegen_inputs_to_outputs:
            if isinstance(sources_field, input_type):
                codegen_sources_fields_with_output.append((sources_field, output_type))
                found = True
        # make sure to include anything where codegen doesn't apply
        if not found:
            codegen_sources_fields_with_output.append((sources_field, type(sources_field)))
    hydrated_dep_sources = await MultiGet(
        Get(
            HydratedSources,
            HydrateSourcesRequest(
                sources,
                for_sources_types=(output_type,),
                enable_codegen=True,
            ),
        )
        for sources, output_type in codegen_sources_fields_with_output
    )

    # I would love to cleanly support relocations to 'src' from 'dependencies' files.
    # But, I don't see any clean approaches to identify which package, generated file,
    # or workspace file needs to be relocated to 'src'.
    # TODO: handle relocations from 'dependencies' to 'src'
    #       deps.nfpm_content_from_dependency_targets

    # This should include at least all files in 'src' fields of nfpm_content_file targets.
    # Other dependency files aren't required since nFPM will ignore anything not configured.
    sandbox_digest = await Get(
        Digest,
        MergeDigests(
            [
                *(package.digest for package in packages),
                # nfpm_content_file 'src' from 'source' field
                nfpm_content_relocated_sources_digest,
                nfpm_content_sources.snapshot.digest,
                # nfpm_content_file 'src' from 'dependencies' field
                *(hydrated.snapshot.digest for hydrated in hydrated_dep_sources),
            ]
        ),
    )

    return NfpmContentSandbox(sandbox_digest)


def rules():
    return [*collect_rules()]
