# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from pathlib import PurePath

from pants.core.goals.package import (
    BuiltPackage,
    BuiltPackageArtifact,
    OutputPathField,
    PackageFieldSet,
)
from pants.core.util_rules.archive import ArchiveFormat, CreateArchive
from pants.engine.addresses import UnparsedAddressInputs
from pants.engine.fs import AddPrefix, Digest, MergeDigests, RemovePrefix, Snapshot
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import (
    COMMON_TARGET_FIELDS,
    AllTargets,
    Dependencies,
    FieldSet,
    FieldSetsPerTarget,
    FieldSetsPerTargetRequest,
    GeneratedSources,
    GenerateSourcesRequest,
    HydratedSources,
    HydrateSourcesRequest,
    MultipleSourcesField,
    OverridesField,
    SingleSourceField,
    SourcesField,
    SpecialCasedDependencies,
    StringField,
    Target,
    TargetFilesGenerator,
    Targets,
    generate_file_based_overrides_field_help_message,
)
from pants.engine.unions import UnionRule
from pants.util.docutil import bin_name
from pants.util.frozendict import FrozenDict
from pants.util.logging import LogLevel
from pants.util.strutil import softwrap

# -----------------------------------------------------------------------------------------------
# `file` and`files` targets
# -----------------------------------------------------------------------------------------------


class FileSourceField(SingleSourceField):
    uses_source_roots = False


class FileTarget(Target):
    alias = "file"
    core_fields = (*COMMON_TARGET_FIELDS, Dependencies, FileSourceField)
    help = softwrap(
        """
        A single loose file that lives outside of code packages.

        Files are placed directly in archives, outside of code artifacts such as Python wheels
        or JVM JARs. The sources of a `file` target are accessed via filesystem APIs, such as
        Python's `open()`, via paths relative to the repository root.
        """
    )


class FilesGeneratingSourcesField(MultipleSourcesField):
    required = True
    uses_source_roots = False


class FilesOverridesField(OverridesField):
    help = generate_file_based_overrides_field_help_message(
        FileTarget.alias,
        (
            "overrides={\n"
            '  "foo.json": {"description": "our customer model"]},\n'
            '  "bar.json": {"description": "our product model"]},\n'
            '  ("foo.json", "bar.json"): {"tags": ["overridden"]},\n'
            "}"
        ),
    )


class FilesGeneratorTarget(TargetFilesGenerator):
    alias = "files"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        FilesGeneratingSourcesField,
        FilesOverridesField,
    )
    generated_target_cls = FileTarget
    copied_fields = COMMON_TARGET_FIELDS
    moved_fields = (Dependencies,)
    help = "Generate a `file` target for each file in the `sources` field."


# -----------------------------------------------------------------------------------------------
# `relocated_files` target
# -----------------------------------------------------------------------------------------------


class RelocatedFilesSourcesField(MultipleSourcesField):
    # We solely register this field for codegen to work.
    alias = "_sources"
    expected_num_files = 0


class RelocatedFilesOriginalTargetsField(SpecialCasedDependencies):
    alias = "files_targets"
    required = True
    help = softwrap(
        """
        Addresses to the original `file` and `files` targets that you want to relocate, such as
        `['//:json_files']`.

        Every target will be relocated using the same mapping. This means
        that every target must include the value from the `src` field in their original path.
        """
    )


class RelocatedFilesSrcField(StringField):
    alias = "src"
    required = True
    help = softwrap(
        """
        The original prefix that you want to replace, such as `src/resources`.

        You can set this field to the empty string to preserve the original path; the value in the `dest`
        field will then be added to the beginning of this original path.
        """
    )


class RelocatedFilesDestField(StringField):
    alias = "dest"
    required = True
    help = softwrap(
        """
        The new prefix that you want to add to the beginning of the path, such as `data`.

        You can set this field to the empty string to avoid adding any new values to the path; the
        value in the `src` field will then be stripped, rather than replaced.
        """
    )


class RelocatedFiles(Target):
    alias = "relocated_files"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        RelocatedFilesSourcesField,
        RelocatedFilesOriginalTargetsField,
        RelocatedFilesSrcField,
        RelocatedFilesDestField,
    )
    help = softwrap(
        """
        Loose files with path manipulation applied.

        Allows you to relocate the files at runtime to something more convenient than their actual
        paths in your project.

        For example, you can relocate `src/resources/project1/data.json` to instead be
        `resources/data.json`. Your other target types can then add this target to their
        `dependencies` field, rather than using the original `files` target.

        To remove a prefix:

            # Results in `data.json`.
            relocated_files(
                files_targets=["src/resources/project1:target"],
                src="src/resources/project1",
                dest="",
            )

        To add a prefix:

            # Results in `images/logo.svg`.
            relocated_files(
                files_targets=["//:logo"],
                src="",
                dest="images",
            )

        To replace a prefix:

            # Results in `new_prefix/project1/data.json`.
            relocated_files(
                files_targets=["src/resources/project1:target"],
                src="src/resources",
                dest="new_prefix",
            )
        """
    )


class RelocateFilesViaCodegenRequest(GenerateSourcesRequest):
    input = RelocatedFilesSourcesField
    output = FileSourceField
    exportable = False


@rule(desc="Relocating loose files for `relocated_files` targets", level=LogLevel.DEBUG)
async def relocate_files(request: RelocateFilesViaCodegenRequest) -> GeneratedSources:
    # Unlike normal codegen, we operate the on the sources of the `files_targets` field, not the
    # `sources` of the original `relocated_sources` target.
    # TODO(#13086): Because we're using `Targets` instead of `UnexpandedTargets`, the
    #  `files` target generator gets replaced by its generated `file` targets. That replacement is
    #  necessary because we only hydrate sources for `FileSourcesField`, which is only for the
    #  `file` target.  That's really subtle!
    original_file_targets = await Get(
        Targets,
        UnparsedAddressInputs,
        request.protocol_target.get(
            RelocatedFilesOriginalTargetsField
        ).to_unparsed_address_inputs(),
    )
    original_files_sources = await MultiGet(
        Get(
            HydratedSources,
            HydrateSourcesRequest(
                tgt.get(SourcesField),
                for_sources_types=(FileSourceField,),
                enable_codegen=True,
            ),
        )
        for tgt in original_file_targets
    )
    snapshot = await Get(
        Snapshot, MergeDigests(sources.snapshot.digest for sources in original_files_sources)
    )

    src_val = request.protocol_target.get(RelocatedFilesSrcField).value
    dest_val = request.protocol_target.get(RelocatedFilesDestField).value
    if src_val:
        snapshot = await Get(Snapshot, RemovePrefix(snapshot.digest, src_val))
    if dest_val:
        snapshot = await Get(Snapshot, AddPrefix(snapshot.digest, dest_val))
    return GeneratedSources(snapshot)


# -----------------------------------------------------------------------------------------------
# `resource` and `resources` target
# -----------------------------------------------------------------------------------------------


class ResourceSourceField(SingleSourceField):
    uses_source_roots = True


class ResourceTarget(Target):
    alias = "resource"
    core_fields = (*COMMON_TARGET_FIELDS, Dependencies, ResourceSourceField)
    help = softwrap(
        """
        A single resource file embedded in a code package and accessed in a
        location-independent manner.

        Resources are embedded in code artifacts such as Python wheels or JVM JARs. The sources
        of a `resources` target are accessed via language-specific resource APIs, such as
        Python's `pkgutil` or JVM's ClassLoader, via paths relative to the target's source root.
        """
    )


class ResourcesGeneratingSourcesField(MultipleSourcesField):
    required = True


class ResourcesOverridesField(OverridesField):
    help = generate_file_based_overrides_field_help_message(
        ResourceTarget.alias,
        (
            "overrides={\n"
            '  "foo.json": {"description": "our customer model"]},\n'
            '  "bar.json": {"description": "our product model"]},\n'
            '  ("foo.json", "bar.json"): {"tags": ["overridden"]},\n'
            "}"
        ),
    )


class ResourcesGeneratorTarget(TargetFilesGenerator):
    alias = "resources"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        ResourcesGeneratingSourcesField,
        ResourcesOverridesField,
    )
    generated_target_cls = ResourceTarget
    copied_fields = COMMON_TARGET_FIELDS
    moved_fields = (Dependencies,)
    help = "Generate a `resource` target for each file in the `sources` field."


@dataclass(frozen=True)
class ResourcesFieldSet(FieldSet):
    required_fields = (ResourceSourceField,)

    sources: ResourceSourceField


@dataclass(frozen=True)
class ResourcesGeneratorFieldSet(FieldSet):
    required_fields = (ResourcesGeneratingSourcesField,)

    sources: ResourcesGeneratingSourcesField


# -----------------------------------------------------------------------------------------------
# `target` generic target
# -----------------------------------------------------------------------------------------------


class GenericTarget(Target):
    alias = "target"
    core_fields = (*COMMON_TARGET_FIELDS, Dependencies)
    help = softwrap(
        """
        A generic target with no specific type.

        This can be used as a generic "bag of dependencies", i.e. you can group several different
        targets into one single target so that your other targets only need to depend on one thing.
        """
    )


# -----------------------------------------------------------------------------------------------
# `Asset` targets (resources and files)
# -----------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class AllAssetTargetsRequest:
    pass


@dataclass(frozen=True)
class AllAssetTargets:
    resources: tuple[Target, ...]
    files: tuple[Target, ...]


@rule(desc="Find all assets in project")
def find_all_assets(
    all_targets: AllTargets,
    _: AllAssetTargetsRequest,
) -> AllAssetTargets:
    resources = []
    files = []
    for tgt in all_targets:
        if tgt.has_field(ResourceSourceField):
            resources.append(tgt)
        if tgt.has_field(FileSourceField):
            files.append(tgt)
    return AllAssetTargets(tuple(resources), tuple(files))


@dataclass(frozen=True)
class AllAssetTargetsByPath:
    resources: FrozenDict[PurePath, frozenset[Target]]
    files: FrozenDict[PurePath, frozenset[Target]]


@rule(desc="Mapping assets by path")
def map_assets_by_path(
    all_asset_targets: AllAssetTargets,
) -> AllAssetTargetsByPath:
    resources_by_path: defaultdict[PurePath, set[Target]] = defaultdict(set)
    for resource_tgt in all_asset_targets.resources:
        path = PurePath(resource_tgt[ResourceSourceField].file_path)
        resources_by_path[path].add(resource_tgt)

    files_by_path: defaultdict[PurePath, set[Target]] = defaultdict(set)
    for file_tgt in all_asset_targets.files:
        files_by_path[PurePath(file_tgt[FileSourceField].file_path)].add(file_tgt)

    return AllAssetTargetsByPath(
        FrozenDict((key, frozenset(values)) for key, values in resources_by_path.items()),
        FrozenDict((key, frozenset(values)) for key, values in files_by_path.items()),
    )


# -----------------------------------------------------------------------------------------------
# `_target_generator_sources_helper` target
# -----------------------------------------------------------------------------------------------


class TargetGeneratorSourcesHelperSourcesField(MultipleSourcesField):
    uses_source_roots = False
    required = True


class TargetGeneratorSourcesHelperTarget(Target):
    """Target generators that work by reading in some source file(s) should also generate this
    target and add it as a dependency to every generated target so that `--changed-since` works
    properly.

    See https://github.com/pantsbuild/pants/issues/13118 for discussion of why this is necessary and
    alternatives considered.
    """

    alias = "_generator_sources_helper"
    core_fields = (*COMMON_TARGET_FIELDS, TargetGeneratorSourcesHelperSourcesField)
    help = softwrap(
        """
        A private helper target type used by some target generators.

        This tracks their `sources` field so that `--changed-since --changed-dependees` works
        properly for generated targets.
        """
    )


# -----------------------------------------------------------------------------------------------
# `archive` target
# -----------------------------------------------------------------------------------------------


class ArchivePackagesField(SpecialCasedDependencies):
    alias = "packages"
    help = softwrap(
        f"""
        Addresses to any targets that can be built with `{bin_name()} package`, e.g.
        `["project:app"]`.\n\nPants will build the assets as if you had run `{bin_name()} package`.
        It will include the results in your archive using the same name they would normally have,
        but without the `--distdir` prefix (e.g. `dist/`).\n\nYou can include anything that can
        be built by `{bin_name()} package`, e.g. a `pex_binary`, `python_awslambda`, or even another
        `archive`.
        """
    )


class ArchiveFilesField(SpecialCasedDependencies):
    alias = "files"
    help = softwrap(
        """
        Addresses to any `file`, `files`, or `relocated_files` targets to include in the
        archive, e.g. `["resources:logo"]`.

        This is useful to include any loose files, like data files,
        image assets, or config files.

        This will ignore any targets that are not `file`, `files`, or
        `relocated_files` targets.

        If you instead want those files included in any packages specified in the `packages`
        field for this target, then use a `resource` or `resources` target and have the original
        package depend on the resources.
        """
    )


class ArchiveFormatField(StringField):
    alias = "format"
    valid_choices = ArchiveFormat
    required = True
    value: str
    help = "The type of archive file to be generated."


class ArchiveTarget(Target):
    alias = "archive"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        OutputPathField,
        ArchivePackagesField,
        ArchiveFilesField,
        ArchiveFormatField,
    )
    help = "A ZIP or TAR file containing loose files and code packages."


@dataclass(frozen=True)
class ArchiveFieldSet(PackageFieldSet):
    required_fields = (ArchiveFormatField,)

    packages: ArchivePackagesField
    files: ArchiveFilesField
    format_field: ArchiveFormatField
    output_path: OutputPathField


@rule(level=LogLevel.DEBUG)
async def package_archive_target(field_set: ArchiveFieldSet) -> BuiltPackage:
    # TODO(#13086): Because we're using `Targets` instead of `UnexpandedTargets`, the
    #  `files` target generator gets replaced by its generated `file` targets. That replacement is
    #  necessary because we only hydrate sources for `FileSourcesField`, which is only for the
    #  `file` target.  That's really subtle!
    package_targets, file_targets = await MultiGet(
        Get(Targets, UnparsedAddressInputs, field_set.packages.to_unparsed_address_inputs()),
        Get(Targets, UnparsedAddressInputs, field_set.files.to_unparsed_address_inputs()),
    )

    package_field_sets_per_target = await Get(
        FieldSetsPerTarget, FieldSetsPerTargetRequest(PackageFieldSet, package_targets)
    )
    packages = await MultiGet(
        Get(BuiltPackage, PackageFieldSet, field_set)
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

    input_snapshot = await Get(
        Snapshot,
        MergeDigests(
            (
                *(package.digest for package in packages),
                *(sources.snapshot.digest for sources in file_sources),
            )
        ),
    )

    output_filename = field_set.output_path.value_or_default(
        file_ending=field_set.format_field.value
    )
    archive = await Get(
        Digest,
        CreateArchive(
            input_snapshot,
            output_filename=output_filename,
            format=ArchiveFormat(field_set.format_field.value),
        ),
    )
    return BuiltPackage(archive, (BuiltPackageArtifact(output_filename),))


def rules():
    return (
        *collect_rules(),
        UnionRule(GenerateSourcesRequest, RelocateFilesViaCodegenRequest),
        UnionRule(PackageFieldSet, ArchiveFieldSet),
    )
