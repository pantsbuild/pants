# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass
from textwrap import dedent

from pants.core.goals.package import (
    BuiltPackage,
    BuiltPackageArtifact,
    OutputPathField,
    PackageFieldSet,
)
from pants.core.util_rules.archive import ArchiveFormat, CreateArchive
from pants.engine.addresses import UnparsedAddressInputs
from pants.engine.fs import (
    AddPrefix,
    Digest,
    MergeDigests,
    PathGlobs,
    Paths,
    RemovePrefix,
    Snapshot,
)
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import (
    COMMON_TARGET_FIELDS,
    Dependencies,
    FieldSetsPerTarget,
    FieldSetsPerTargetRequest,
    GeneratedSources,
    GeneratedTargets,
    GenerateSourcesRequest,
    GenerateTargetsRequest,
    HydratedSources,
    HydrateSourcesRequest,
    MultipleSourcesField,
    OverridesField,
    SingleSourceField,
    SourcesField,
    SourcesPaths,
    SourcesPathsRequest,
    SpecialCasedDependencies,
    StringField,
    Target,
    Targets,
    generate_file_based_overrides_field_help_message,
    generate_file_level_targets,
)
from pants.engine.unions import UnionMembership, UnionRule
from pants.option.global_options import FilesNotFoundBehavior
from pants.util.logging import LogLevel

# -----------------------------------------------------------------------------------------------
# `file` and`files` targets
# -----------------------------------------------------------------------------------------------


class FileSourceField(SingleSourceField):
    uses_source_roots = False


class FileTarget(Target):
    alias = "file"
    core_fields = (*COMMON_TARGET_FIELDS, Dependencies, FileSourceField)
    help = (
        "A single loose file that lives outside of code packages.\n\n"
        "Files are placed directly in archives, outside of code artifacts such as Python wheels "
        "or JVM JARs. The sources of a `file` target are accessed via filesystem APIs, such as "
        "Python's `open()`, via paths relative to the repository root."
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


class FilesGeneratorTarget(Target):
    alias = "files"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        Dependencies,
        FilesGeneratingSourcesField,
        FilesOverridesField,
    )
    help = "Generate a `file` target for each file in the `sources` field."


class GenerateTargetsFromFiles(GenerateTargetsRequest):
    generate_from = FilesGeneratorTarget


@rule
async def generate_targets_from_files(
    request: GenerateTargetsFromFiles,
    union_membership: UnionMembership,
    files_not_found_behavior: FilesNotFoundBehavior,
) -> GeneratedTargets:
    sources_paths = await Get(
        SourcesPaths, SourcesPathsRequest(request.generator[FilesGeneratingSourcesField])
    )

    all_overrides = {}
    overrides_field = request.generator[OverridesField]
    if overrides_field.value:
        _all_override_paths = await MultiGet(
            Get(Paths, PathGlobs, path_globs)
            for path_globs in overrides_field.to_path_globs(files_not_found_behavior)
        )
        all_overrides = overrides_field.flatten_paths(
            dict(zip(_all_override_paths, overrides_field.value.values()))
        )

    return generate_file_level_targets(
        FileTarget,
        request.generator,
        sources_paths.files,
        union_membership,
        add_dependencies_on_all_siblings=False,
        overrides=all_overrides,
    )


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
    help = (
        "Addresses to the original `file` and `files` targets that you want to relocate, such as "
        "`['//:json_files']`.\n\nEvery target will be relocated using the same mapping. This means "
        "that every target must include the value from the `src` field in their original path."
    )


class RelocatedFilesSrcField(StringField):
    alias = "src"
    required = True
    help = (
        "The original prefix that you want to replace, such as `src/resources`.\n\nYou can set "
        "this field to the empty string to preserve the original path; the value in the `dest` "
        "field will then be added to the beginning of this original path."
    )


class RelocatedFilesDestField(StringField):
    alias = "dest"
    required = True
    help = (
        "The new prefix that you want to add to the beginning of the path, such as `data`.\n\nYou "
        "can set this field to the empty string to avoid adding any new values to the path; the "
        "value in the `src` field will then be stripped, rather than replaced."
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
    help = (
        "Loose files with path manipulation applied.\n\nAllows you to relocate the files at "
        "runtime to something more convenient than their actual paths in your project.\n\nFor "
        "example, you can relocate `src/resources/project1/data.json` to instead be "
        "`resources/data.json`. Your other target types can then add this target to their "
        "`dependencies` field, rather than using the original `files` target.\n\n"
    ) + dedent(
        """\
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
            HydrateSourcesRequest(tgt.get(SourcesField), for_sources_types=(FileSourceField,)),
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
    help = (
        "A single resource file embedded in a code package and accessed in a "
        "location-independent manner.\n\n"
        "Resources are embedded in code artifacts such as Python wheels or JVM JARs. The sources "
        "of a `resources` target are accessed via language-specific resource APIs, such as "
        "Python's `pkgutil` or JVM's ClassLoader, via paths relative to the target's source root."
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


class ResourcesGeneratorTarget(Target):
    alias = "resources"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        Dependencies,
        ResourcesGeneratingSourcesField,
        ResourcesOverridesField,
    )
    help = "Generate a `resource` target for each file in the `sources` field."


class GenerateTargetsFromResources(GenerateTargetsRequest):
    generate_from = ResourcesGeneratorTarget


@rule
async def generate_targets_from_resources(
    request: GenerateTargetsFromResources,
    union_membership: UnionMembership,
    files_not_found_behavior: FilesNotFoundBehavior,
) -> GeneratedTargets:
    sources_paths = await Get(
        SourcesPaths, SourcesPathsRequest(request.generator[ResourcesGeneratingSourcesField])
    )

    all_overrides = {}
    overrides_field = request.generator[OverridesField]
    if overrides_field.value:
        _all_override_paths = await MultiGet(
            Get(Paths, PathGlobs, path_globs)
            for path_globs in overrides_field.to_path_globs(files_not_found_behavior)
        )
        all_overrides = overrides_field.flatten_paths(
            dict(zip(_all_override_paths, overrides_field.value.values()))
        )

    return generate_file_level_targets(
        ResourceTarget,
        request.generator,
        sources_paths.files,
        union_membership,
        add_dependencies_on_all_siblings=False,
        overrides=all_overrides,
    )


# -----------------------------------------------------------------------------------------------
# `target` generic target
# -----------------------------------------------------------------------------------------------


class GenericTarget(Target):
    alias = "target"
    core_fields = (*COMMON_TARGET_FIELDS, Dependencies)
    help = (
        'A generic target with no specific type.\n\nThis can be used as a generic "bag of '
        'dependencies", i.e. you can group several different targets into one single target so '
        "that your other targets only need to depend on one thing."
    )


# -----------------------------------------------------------------------------------------------
# `archive` target
# -----------------------------------------------------------------------------------------------


class ArchivePackagesField(SpecialCasedDependencies):
    alias = "packages"
    help = (
        "Addresses to any targets that can be built with `./pants package`, e.g. "
        '`["project:app"]`.\n\nPants will build the assets as if you had run `./pants package`. '
        "It will include the results in your archive using the same name they would normally have, "
        "but without the `--distdir` prefix (e.g. `dist/`).\n\nYou can include anything that can "
        "be built by `./pants package`, e.g. a `pex_binary`, `python_awslambda`, or even another "
        "`archive`."
    )


class ArchiveFilesField(SpecialCasedDependencies):
    alias = "files"
    help = (
        "Addresses to any `file`, `files`, or `relocated_files` targets to include in the "
        'archive, e.g. `["resources:logo"]`.\n\n'
        "This is useful to include any loose files, like data files, "
        "image assets, or config files.\n\n"
        "This will ignore any targets that are not `file`, `files`, or "
        "`relocated_files` targets.\n\n"
        "If you instead want those files included in any packages specified in the `packages` "
        "field for this target, then use a `resource` or `resources` target and have the original "
        "package depend on the resources."
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
        UnionRule(GenerateTargetsRequest, GenerateTargetsFromFiles),
        UnionRule(GenerateTargetsRequest, GenerateTargetsFromResources),
        UnionRule(GenerateSourcesRequest, RelocateFilesViaCodegenRequest),
        UnionRule(PackageFieldSet, ArchiveFieldSet),
    )
