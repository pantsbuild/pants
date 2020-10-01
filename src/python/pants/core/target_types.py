# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from typing import Tuple

from pants.engine.addresses import AddressInput
from pants.engine.fs import AddPrefix, MergeDigests, RemovePrefix, Snapshot
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import (
    COMMON_TARGET_FIELDS,
    Dependencies,
    GeneratedSources,
    GenerateSourcesRequest,
    HydratedSources,
    HydrateSourcesRequest,
    Sources,
    StringField,
    StringSequenceField,
    Target,
    WrappedTarget,
)
from pants.engine.unions import UnionRule
from pants.util.logging import LogLevel

# -----------------------------------------------------------------------------------------------
# `files` target
# -----------------------------------------------------------------------------------------------


class FilesSources(Sources):
    required = True


class Files(Target):
    """A collection of loose files which do not have their source roots stripped.

    The sources of a `files` target can be accessed via language-specific APIs, such as Python's
    `open()`. Unlike the similar `resources()` target type, Pants will not strip the source root of
    `files()`, meaning that `src/python/project/f1.txt` will not be stripped down to
    `project/f1.txt`.
    """

    alias = "files"
    core_fields = (*COMMON_TARGET_FIELDS, Dependencies, FilesSources)


# -----------------------------------------------------------------------------------------------
# `relocated_files` target
# -----------------------------------------------------------------------------------------------


class RelocatedFilesSources(Sources):
    # We solely register this field for codegen to work.
    alias = "_sources"
    expected_num_files = 0


class RelocatedFilesOriginalTargets(StringSequenceField):
    """Addresses to the original `files()` targets that you want to relocate, such as
    `['//:json_files']`.

    Every target will be relocated using the same mapping. This means that every target must include
    the value from the `src` field in their original path.
    """

    alias = "files_targets"
    required = True
    value: Tuple[str, ...]


class RelocatedFilesSrcField(StringField):
    """The original prefix that you want to replace, such as `src/resources`.

    You can set this field to `""` to preserve the original path; the value in the `dest` field will
    then be added to the beginning of this original path.
    """

    alias = "src"
    required = True


class RelocatedFilesDestField(StringField):
    """The new prefix that you want to add to the beginning of the path, such as `data`.

    You can set this field to `""` to avoid adding any new values to the path; the value in the
    `src` field will then be stripped, rather than replaced.
    """

    alias = "dest"
    required = True


class RelocatedFiles(Target):
    """Relocate the paths for `files()` targets at runtime to something more convenient than the
    default of their actual paths in your project.

    For example, you can relocate `src/resources/project1/data.json` to instead be
    `resources/data.json`. Your other target types can then add this target to their
    `dependencies` field, rather than using the original `files` target.

    To remove a prefix:

        # Results in `data.json`.
        relocated_files(
            file_targets=["src/resources/project1:target"],
            src="src/resources/project1",
            dest="",
        )

    To add a prefix:

        # Results in `images/logo.svg`.
        relocated_files(
            file_targets=["//:logo"],
            src="",
            dest="images",
        )

    To replace a prefix:

        # Results in `new_prefix/project1/data.json`.
        relocated_files(
            file_targets=["src/resources/project1:target"],
            src="src/resources",
            dest="new_prefix",
        )
    """

    alias = "relocated_files"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        RelocatedFilesSources,
        RelocatedFilesOriginalTargets,
        RelocatedFilesSrcField,
        RelocatedFilesDestField,
    )


class RelocateFilesViaCodegenRequest(GenerateSourcesRequest):
    input = RelocatedFilesSources
    output = FilesSources


@rule(desc="Relocating loose files for `relocated_files` targets", level=LogLevel.DEBUG)
async def relocate_files(request: RelocateFilesViaCodegenRequest) -> GeneratedSources:
    # Unlike normal codegen, we operate the on the sources of the `files_targets` field, not the
    # `sources` of the original `relocated_sources` target.
    original_files_targets = await MultiGet(
        Get(WrappedTarget, AddressInput, AddressInput.parse(v))
        for v in request.protocol_target.get(RelocatedFilesOriginalTargets).value
    )
    original_files_sources = await MultiGet(
        Get(HydratedSources, HydrateSourcesRequest(wrapped_tgt.target.get(Sources)))
        for wrapped_tgt in original_files_targets
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
# `resources` target
# -----------------------------------------------------------------------------------------------


class ResourcesSources(Sources):
    required = True


class Resources(Target):
    """A collection of loose files.

    The sources of a `resources` target can be accessed via language-specific APIs, such as Python's
    `open()`. Resources are meant to be included in deployable units like JARs or Python wheels.
    Unlike the similar `files()` target type, Pants will strip the source root of `resources()`,
    meaning that `src/python/project/f1.txt` will be stripped down to `project/f1.txt`.
    """

    alias = "resources"
    core_fields = (*COMMON_TARGET_FIELDS, Dependencies, ResourcesSources)


# -----------------------------------------------------------------------------------------------
# `target` generic target
# -----------------------------------------------------------------------------------------------


class GenericTarget(Target):
    """A generic target with no specific target type.

    This can be used as a generic "bag of dependencies", i.e. you can group several different
    targets into one single target so that your other targets only need to depend on one thing.
    """

    alias = "target"
    core_fields = (*COMMON_TARGET_FIELDS, Dependencies)


def rules():
    return (*collect_rules(), UnionRule(GenerateSourcesRequest, RelocateFilesViaCodegenRequest))
