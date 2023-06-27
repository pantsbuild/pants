# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import builtins
import dataclasses
import os
import urllib.parse
from collections import defaultdict
from dataclasses import dataclass
from pathlib import PurePath
from typing import Generic, Optional, Sequence, TypeVar, Union, cast

from pants.core.goals import package
from pants.core.goals.package import (
    BuiltPackage,
    BuiltPackageArtifact,
    EnvironmentAwarePackageRequest,
    OutputPathField,
    PackageFieldSet,
)
from pants.core.util_rules.archive import ArchiveFormat, CreateArchive
from pants.core.util_rules.archive import rules as archive_rules
from pants.engine.addresses import Address, UnparsedAddressInputs
from pants.engine.fs import (
    AddPrefix,
    CreateDigest,
    Digest,
    DownloadFile,
    FileDigest,
    FileEntry,
    MergeDigests,
    PathGlobs,
    RemovePrefix,
    Snapshot,
)
from pants.engine.platform import Platform
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
    InvalidFieldTypeException,
    MultipleSourcesField,
    OptionalSingleSourceField,
    OverridesField,
    SingleSourceField,
    SourcesField,
    SpecialCasedDependencies,
    StringField,
    Target,
    TargetFilesGenerator,
    Targets,
    generate_file_based_overrides_field_help_message,
    generate_multiple_sources_field_help_message,
)
from pants.engine.unions import UnionRule
from pants.option.global_options import UnmatchedBuildFileGlobs
from pants.util.docutil import bin_name
from pants.util.frozendict import FrozenDict
from pants.util.logging import LogLevel
from pants.util.strutil import help_text, softwrap

# -----------------------------------------------------------------------------------------------
# `per_platform` object
# -----------------------------------------------------------------------------------------------
_T = TypeVar("_T")


@dataclass(frozen=True)
class per_platform(Generic[_T]):
    """An object containing differing homogeneous platform-dependent values.

    The values should be evaluated for the execution environment, and not the host environment
    (I.e. it should be evaluated in a `rule` which requests `Platform`).

    Expected usage is roughly:

    ```python
    class MyFieldType(...):
        value = str | per_platform[str]

        @classmethod
        def compute_value(  # type: ignore[override]
            cls,
            raw_value: Optional[Union[str, per_platform[str]]],
            address: Address,
        ) -> Optional[Union[str, per_platform[str]]]:
            if isinstance(raw_value, per_platform):
                # NOTE: Ensure the values are homogenous
                raw_value.check_types(str)

            return raw_value

    ...

    @rule
    async def my_rule(..., platform: Platform) -> ...:
        field_value = target[MyFieldType].value

        if isinstance(field_value, per_platform):
            field_value = field_value.get_value_for_platform(platform)

        ...
    ```

    NOTE: Support for this object should be heavily weighed, as it would be innaproriate to use in
    certain contexts (such as the `source` field in a `foo_source` target, where the intent is to
    support differing source files based on platform. The result would be that dependency inference
    (and therefore the dependencies field) wouldn't be knowable on the host, which is not something
    the engine can support yet).
    """

    linux_arm64: _T | None = None
    linux_x86_64: _T | None = None
    macos_arm64: _T | None = None
    macos_x86_64: _T | None = None

    def check_types(self, type_: type) -> None:
        fields_and_values = [
            (field.name, getattr(self, field.name)) for field in dataclasses.fields(self)
        ]
        fields_with_values = {name: value for name, value in fields_and_values if value is not None}
        if not fields_with_values:
            raise ValueError("`per_platform` must be given at least one platform value.")

        bad_typed_fields = [
            (name, type(value).__name__)
            for name, value in fields_with_values.items()
            if not isinstance(value, type_)
        ]
        if bad_typed_fields:
            raise TypeError(
                f"The following fields of a `per_platform` object were expected to be of type `{type_.__name__}`:"
                + ' "'
                + ", ".join(f"{name} of type '{typename}'" for name, typename in bad_typed_fields)
                + '".'
            )

    def get_value_for_platform(self, platform: Platform) -> _T:
        value = getattr(self, platform.value)
        if value is None:
            raise ValueError(
                f"A request was made to resolve a `per_platform` on `{platform.value}`"
                + " but the value was `None`. Please specify a value."
            )
        return cast("_T", value)


# -----------------------------------------------------------------------------------------------
# Asset target helpers
# -----------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class http_source:
    url: str
    len: int
    sha256: str
    # Defaults to last part of the URL path (E.g. `index.html`)
    filename: str

    def __init__(self, url: str, *, len: int, sha256: str, filename: str = ""):
        for field in dataclasses.fields(self):
            value = locals()[field.name]
            if not isinstance(value, getattr(builtins, cast(str, field.type))):
                raise TypeError(f"`{field.name}` must be a `{field.type}`, got `{type(value)!r}`.")

        object.__setattr__(self, "url", url)
        object.__setattr__(self, "len", len)
        object.__setattr__(self, "sha256", sha256)
        object.__setattr__(
            self, "filename", filename or urllib.parse.urlparse(url).path.rsplit("/", 1)[-1]
        )

        self.__post_init__()

    def __post_init__(self):
        if not self.filename:
            raise ValueError(
                softwrap(
                    f"""
                    Couldn't deduce filename from `url`: '{self.url}'.

                    Please specify the `filename` argument.
                    """
                )
            )
        if "\\" in self.filename or "/" in self.filename:
            raise ValueError(
                f"`filename` cannot contain a path separator, but was set to '{self.filename}'"
            )


class AssetSourceField(SingleSourceField):
    value: str | http_source | per_platform[http_source]  # type: ignore[assignment]
    # @TODO: Don't document http_source, link to it once https://github.com/pantsbuild/pants/issues/14832
    # is implemented.
    help = help_text(
        """
        The source of this target.

        If a string is provided, represents a path that is relative to the BUILD file's directory,
        e.g. `source='example.ext'`.

        If an `http_source` is provided, represents the network location to download the source from.
        The downloaded file will exist in the sandbox in the same directory as the target.

        `http_source` has the following signature:

            http_source(url: str, *, len: int, sha256: str, filename: str = "")

        The filename defaults to the last part of the URL path (e.g. `example.ext`), but can also be
        specified if you wish to have control over the file name. You cannot, however, specify a
        path separator to download the file into a subdirectory (you must declare a target in desired
        subdirectory).

        You can easily get the len and checksum with the following command:

            curl -L $URL | tee >(wc -c) >(shasum -a 256) >/dev/null

        If a `per_platform` is provided, represents a mapping from platform to `http_source`, where
        the platform is one of (`linux_arm64`, `linux_x86_64`, `macos_arm64`, `macos_x86_64`) and is
        resolved in the execution target. Each `http_source` value MUST have the same filename provided.
        """
    )

    @classmethod
    def compute_value(  # type: ignore[override]
        cls,
        raw_value: Optional[Union[str, http_source, per_platform[http_source]]],
        address: Address,
    ) -> Optional[Union[str, http_source, per_platform[http_source]]]:
        if raw_value is None or isinstance(raw_value, str):
            return super().compute_value(raw_value, address)
        elif isinstance(raw_value, per_platform):
            raw_value.check_types(http_source)
            value_as_dict = dataclasses.asdict(raw_value)
            filenames = {
                source["filename"] for source in value_as_dict.values() if source is not None
            }
            if len(filenames) > 1:
                raise ValueError(
                    "Every `http_source` in the `per_platform` must have the same `filename`,"
                    + f" but found: {', '.join(sorted(filenames))}"
                )

        elif not isinstance(raw_value, http_source):
            raise InvalidFieldTypeException(
                address,
                cls.alias,
                raw_value,
                expected_type="a string, an `http_source` object, or a `per_platform[http_source]` object.",
            )
        return raw_value

    def validate_resolved_files(self, files: Sequence[str]) -> None:
        if isinstance(self.value, str):
            super().validate_resolved_files(files)

    @property
    def globs(self) -> tuple[str, ...]:
        if isinstance(self.value, str):
            return (self.value,)
        return ()

    @property
    def file_path(self) -> str:
        assert self.value
        filename = (
            self.value
            if isinstance(self.value, str)
            else self.value.filename
            if isinstance(self.value, http_source)
            else next(
                source["filename"]
                for source in dataclasses.asdict(self.value).values()
                if source is not None
            )
        )
        return os.path.join(self.address.spec_path, filename)


async def _hydrate_asset_source(
    request: GenerateSourcesRequest, platform: Platform
) -> GeneratedSources:
    target = request.protocol_target
    source_field = target[AssetSourceField]
    if isinstance(source_field.value, str):
        return GeneratedSources(request.protocol_sources)

    source = source_field.value
    if isinstance(source, per_platform):
        source = source.get_value_for_platform(platform)

    file_digest = FileDigest(source.sha256, source.len)
    # NB: This just has to run, we don't actually need the result because we know the Digest's
    # FileEntry metadata.
    await Get(Digest, DownloadFile(source.url, file_digest))
    snapshot = await Get(
        Snapshot,
        CreateDigest(
            [
                FileEntry(
                    path=source_field.file_path,
                    file_digest=file_digest,
                )
            ]
        ),
    )

    return GeneratedSources(snapshot)


# -----------------------------------------------------------------------------------------------
# `file` and `files` targets
# -----------------------------------------------------------------------------------------------
class FileSourceField(AssetSourceField):
    uses_source_roots = False


class FileDependenciesField(Dependencies):
    pass


class FileTarget(Target):
    alias = "file"
    core_fields = (*COMMON_TARGET_FIELDS, FileDependenciesField, FileSourceField)
    help = help_text(
        """
        A single loose file that lives outside of code packages.

        Files are placed directly in archives, outside of code artifacts such as Python wheels
        or JVM JARs. The sources of a `file` target are accessed via filesystem APIs, such as
        Python's `open()`, via paths relative to the repository root.
        """
    )


class GenerateFileSourceRequest(GenerateSourcesRequest):
    input = FileSourceField
    output = FileSourceField


@rule
async def hydrate_file_source(
    request: GenerateFileSourceRequest, platform: Platform
) -> GeneratedSources:
    return await _hydrate_asset_source(request, platform)


class FilesGeneratingSourcesField(MultipleSourcesField):
    required = True
    uses_source_roots = False
    help = generate_multiple_sources_field_help_message(
        "Example: `sources=['example.txt', 'new_*.md', '!old_ignore.csv']`"
    )


class FilesOverridesField(OverridesField):
    help = generate_file_based_overrides_field_help_message(
        FileTarget.alias,
        """
        overrides={
            "foo.json": {"description": "our customer model"]},
            "bar.json": {"description": "our product model"]},
            ("foo.json", "bar.json"): {"tags": ["overridden"]},
        }
        """,
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
    moved_fields = (FileDependenciesField,)
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
    help = help_text(
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
    help = help_text(
        """
        The original prefix that you want to replace, such as `src/resources`.

        You can set this field to the empty string to preserve the original path; the value in the `dest`
        field will then be added to the beginning of this original path.
        """
    )


class RelocatedFilesDestField(StringField):
    alias = "dest"
    required = True
    help = help_text(
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
    help = help_text(
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


class ResourceDependenciesField(Dependencies):
    pass


class ResourceSourceField(AssetSourceField):
    uses_source_roots = True


class ResourceTarget(Target):
    alias = "resource"
    core_fields = (*COMMON_TARGET_FIELDS, ResourceDependenciesField, ResourceSourceField)
    help = help_text(
        """
        A single resource file embedded in a code package and accessed in a
        location-independent manner.

        Resources are embedded in code artifacts such as Python wheels or JVM JARs. The sources
        of a `resources` target are accessed via language-specific resource APIs, such as
        Python's `pkgutil` or JVM's ClassLoader, via paths relative to the target's source root.
        """
    )


class GenerateResourceSourceRequest(GenerateSourcesRequest):
    input = ResourceSourceField
    output = ResourceSourceField


@rule
async def hydrate_resource_source(
    request: GenerateResourceSourceRequest, platform: Platform
) -> GeneratedSources:
    return await _hydrate_asset_source(request, platform)


class ResourcesGeneratingSourcesField(MultipleSourcesField):
    required = True
    help = generate_multiple_sources_field_help_message(
        "Example: `sources=['example.txt', 'new_*.md', '!old_ignore.csv']`"
    )


class ResourcesOverridesField(OverridesField):
    help = generate_file_based_overrides_field_help_message(
        ResourceTarget.alias,
        """
        overrides={
            "foo.json": {"description": "our customer model"]},
            "bar.json": {"description": "our product model"]},
            ("foo.json", "bar.json"): {"tags": ["overridden"]},
        }
        """,
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
    moved_fields = (ResourceDependenciesField,)
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


class GenericTargetDependenciesField(Dependencies):
    pass


class GenericTarget(Target):
    alias = "target"
    core_fields = (*COMMON_TARGET_FIELDS, GenericTargetDependenciesField)
    help = help_text(
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
class AllAssetTargets:
    resources: tuple[Target, ...]
    files: tuple[Target, ...]


@rule(desc="Find all assets in project")
def find_all_assets(all_targets: AllTargets) -> AllAssetTargets:
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
        resources_by_path[PurePath(resource_tgt[ResourceSourceField].file_path)].add(resource_tgt)

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


class TargetGeneratorSourcesHelperSourcesField(SingleSourceField):
    uses_source_roots = False
    required = True


class TargetGeneratorSourcesHelperTarget(Target):
    """Target generators that work by reading in some source file(s) should also generate this
    target once per file, and add it as a dependency to every generated target so that `--changed-
    since` works properly.

    See https://github.com/pantsbuild/pants/issues/13118 for discussion of why this is necessary and
    alternatives considered.
    """

    alias = "_generator_sources_helper"
    core_fields = (*COMMON_TARGET_FIELDS, TargetGeneratorSourcesHelperSourcesField)
    help = help_text(
        """
        A private helper target type used by some target generators.

        This tracks their `source` / `sources` field so that `--changed-since --changed-dependents`
        works properly for generated targets.
        """
    )


# -----------------------------------------------------------------------------------------------
# `archive` target
# -----------------------------------------------------------------------------------------------


class ArchivePackagesField(SpecialCasedDependencies):
    alias = "packages"
    help = help_text(
        f"""
        Addresses to any targets that can be built with `{bin_name()} package`, e.g.
        `["project:app"]`.\n\nPants will build the assets as if you had run `{bin_name()} package`.
        It will include the results in your archive using the same name they would normally have,
        but without the `--distdir` prefix (e.g. `dist/`).\n\nYou can include anything that can
        be built by `{bin_name()} package`, e.g. a `pex_binary`, `python_aws_lambda_function`, or even another
        `archive`.
        """
    )


class ArchiveFilesField(SpecialCasedDependencies):
    alias = "files"
    help = help_text(
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


# -----------------------------------------------------------------------------------------------
# `_lockfile` and `_lockfiles` targets
# -----------------------------------------------------------------------------------------------


class LockfileSourceField(OptionalSingleSourceField):
    """Source field for synthesized `_lockfile` targets.

    It is special in that it always ignores any missing files, regardless of the global
    `--unmatched-build-file-globs` option.
    """

    uses_source_roots = False
    required = True
    value: str

    def path_globs(self, unmatched_build_file_globs: UnmatchedBuildFileGlobs) -> PathGlobs:  # type: ignore[misc]
        return super().path_globs(UnmatchedBuildFileGlobs.ignore())


class LockfileDependenciesField(Dependencies):
    pass


class LockfileTarget(Target):
    alias = "_lockfile"
    core_fields = (*COMMON_TARGET_FIELDS, LockfileSourceField, LockfileDependenciesField)
    help = help_text(
        """
        A target for lockfiles in order to include them in the dependency graph of other targets.

        This tracks them so that `--changed-since --changed-dependents` works properly for targets
        relying on a particular lockfile.
        """
    )


class LockfilesGeneratorSourcesField(MultipleSourcesField):
    """Sources field for synthesized `_lockfiles` targets.

    It is special in that it always ignores any missing files, regardless of the global
    `--unmatched-build-file-globs` option.
    """

    help = generate_multiple_sources_field_help_message("Example: `sources=['example.lock']`")

    def path_globs(self, unmatched_build_file_globs: UnmatchedBuildFileGlobs) -> PathGlobs:  # type: ignore[misc]
        return super().path_globs(UnmatchedBuildFileGlobs.ignore())


class LockfilesGeneratorTarget(TargetFilesGenerator):
    alias = "_lockfiles"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        LockfilesGeneratorSourcesField,
    )
    generated_target_cls = LockfileTarget
    copied_fields = COMMON_TARGET_FIELDS
    moved_fields = (LockfileDependenciesField,)
    help = "Generate a `_lockfile` target for each file in the `sources` field."


def rules():
    return (
        *collect_rules(),
        *archive_rules(),
        *package.rules(),
        UnionRule(GenerateSourcesRequest, GenerateResourceSourceRequest),
        UnionRule(GenerateSourcesRequest, GenerateFileSourceRequest),
        UnionRule(GenerateSourcesRequest, RelocateFilesViaCodegenRequest),
        UnionRule(PackageFieldSet, ArchiveFieldSet),
    )
