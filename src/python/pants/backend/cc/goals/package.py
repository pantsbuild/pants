# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import PurePath
from typing import Iterable

from pants.backend.cc.target_types import (
    CCContrivedField,
    CCDependenciesField,
    CCFieldSet,
    CCHeadersField,
    CCLinkTypeField,
)
from pants.backend.cc.util_rules.compile import CompileCCSourceRequest, FallibleCompiledCCObject
from pants.backend.cc.util_rules.link import LinkCCObjectsRequest, LinkedCCObjects
from pants.build_graph.address import Address
from pants.core.goals.package import (
    BuiltPackage,
    BuiltPackageArtifact,
    OutputPathField,
    PackageFieldSet,
)
from pants.core.goals.run import RunDebugAdapterRequest, RunFieldSet, RunRequest
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.engine.internals.native_engine import AddPrefix, Digest, MergeDigests
from pants.engine.internals.selectors import Get, MultiGet
from pants.engine.rules import Rule, collect_rules, rule, rule_helper
from pants.engine.target import (
    DependenciesRequest,
    SourcesField,
    Targets,
    TransitiveTargets,
    TransitiveTargetsRequest,
)
from pants.engine.unions import UnionRule
from pants.util.logging import LogLevel

logger = logging.getLogger(__name__)

# -----------------------------------------------------------------------------------------------
# Common rule helpers
# -----------------------------------------------------------------------------------------------


@rule_helper
async def _transitive_field_sets(address: Address) -> list[CCFieldSet]:
    # Grab all dependency targets for this binary (i.e. CCSourceTarget(s) + CCLibraryTarget(s))
    # TODO: Handle cc_library when it become availables, right now, sources are only allowable input
    transitive_targets = await Get(TransitiveTargets, TransitiveTargetsRequest([address]))

    # Create Field Sets from transitive source targets, in order to pass to compilation
    return [CCFieldSet.create(target) for target in transitive_targets.dependencies]


@rule_helper
async def _compile_transitive_targets(cc_field_sets: Iterable[CCFieldSet]) -> Digest:
    # TODO: Should this be Fallible, or just Compiled?
    compiled_objects = await MultiGet(
        Get(FallibleCompiledCCObject, CompileCCSourceRequest(field_set))
        for field_set in cc_field_sets
    )

    # Merge all individual compiled objects into a single digest
    return await Get(
        Digest, MergeDigests([obj.process_result.output_digest for obj in compiled_objects])
    )


# -----------------------------------------------------------------------------------------------
# `cc_library` targets
# -----------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class CCLibraryFieldSet(PackageFieldSet):
    required_fields = (CCDependenciesField, CCLinkTypeField)

    dependencies: CCDependenciesField
    headers: CCHeadersField
    link_type: CCLinkTypeField
    output_path: OutputPathField


@rule(desc="Package CC library", level=LogLevel.DEBUG)
async def package_cc_library(
    field_set: CCLibraryFieldSet,
) -> BuiltPackage:
    cc_field_sets = await _transitive_field_sets(field_set.address)
    digest = await _compile_transitive_targets(cc_field_sets)

    # If any objects were compiled in c++, they need to be linked in c++
    language = next(
        (
            language
            for field_set in cc_field_sets
            if (language := field_set.language.normalized_value()) == "c++"
        ),
        "c",
    )
    output_filename = PurePath(field_set.output_path.value_or_default(file_ending=None))
    library = await Get(
        LinkedCCObjects,
        LinkCCObjectsRequest(
            digest,
            output_filename.name,
            compile_language=language,
            link_type=field_set.link_type.value,
        ),
    )

    # Export headers as-is
    logger.debug(field_set.headers)

    header_targets = await Get(Targets, DependenciesRequest(field_set.headers))
    header_files = await Get(
        SourceFiles, SourceFilesRequest([tgt[SourcesField] for tgt in header_targets])
    )

    renamed_output_digest = await Get(
        Digest, AddPrefix(library.digest, str(output_filename.parent))
    )
    renamed_output_digest = await Get(
        Digest, MergeDigests([renamed_output_digest, header_files.snapshot.digest])
    )

    library_artifact = BuiltPackageArtifact(relpath=str(output_filename))
    return BuiltPackage(renamed_output_digest, (library_artifact,))


# -----------------------------------------------------------------------------------------------
# `cc_binary` targets
# -----------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class CCBinaryFieldSet(PackageFieldSet, RunFieldSet):
    required_fields = (
        CCContrivedField,
        CCDependenciesField,
    )

    dependencies: CCDependenciesField
    output_path: OutputPathField


@rule(desc="Package CC binary", level=LogLevel.DEBUG)
async def package_cc_binary(
    field_set: CCBinaryFieldSet,
) -> BuiltPackage:
    cc_field_sets = await _transitive_field_sets(field_set.address)
    digest = await _compile_transitive_targets(cc_field_sets)

    # If any objects were compiled in c++, they need to be linked in c++
    language = next(
        (
            language
            for field_set in cc_field_sets
            if (language := field_set.language.normalized_value()) == "c++"
        ),
        "c",
    )
    output_filename = PurePath(field_set.output_path.value_or_default(file_ending=None))
    binary = await Get(
        LinkedCCObjects,
        LinkCCObjectsRequest(digest, output_filename.name, compile_language=language),
    )

    renamed_output_digest = await Get(Digest, AddPrefix(binary.digest, str(output_filename.parent)))
    artifact = BuiltPackageArtifact(relpath=str(output_filename))
    return BuiltPackage(renamed_output_digest, (artifact,))


@rule(level=LogLevel.DEBUG)
async def run_cc_binary(field_set: CCBinaryFieldSet) -> RunRequest:
    binary = await Get(BuiltPackage, PackageFieldSet, field_set)
    artifact_relpath = binary.artifacts[0].relpath
    assert artifact_relpath is not None
    return RunRequest(digest=binary.digest, args=(os.path.join("{chroot}", artifact_relpath),))


@rule(level=LogLevel.DEBUG)
async def cc_binary_run_debug_adapter_request(
    field_set: CCBinaryFieldSet,
) -> RunDebugAdapterRequest:
    raise NotImplementedError(
        "Debugging a CC binary using a debug adapter has not yet been implemented."
    )


def rules() -> Iterable[Rule | UnionRule]:
    return (
        *collect_rules(),
        UnionRule(PackageFieldSet, CCLibraryFieldSet),
        UnionRule(PackageFieldSet, CCBinaryFieldSet),
        UnionRule(RunFieldSet, CCBinaryFieldSet),
    )
