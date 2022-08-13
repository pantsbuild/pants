# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import PurePath
from typing import Iterable

from pants.backend.cc.subsystems.toolchain import CCSubsystem, CCToolchain
from pants.backend.cc.target_types import CCDependenciesField, CCFieldSet
from pants.backend.cc.util_rules.compile import CompileCCSourceRequest, FallibleCompiledCCObject
from pants.backend.cc.util_rules.link import LinkCCBinaryRequest, LinkedCCBinary
from pants.core.goals.package import (
    BuiltPackage,
    BuiltPackageArtifact,
    OutputPathField,
    PackageFieldSet,
)
from pants.core.goals.run import RunDebugAdapterRequest, RunFieldSet, RunRequest
from pants.engine.internals.native_engine import AddPrefix, Digest, MergeDigests
from pants.engine.internals.selectors import Get, MultiGet
from pants.engine.rules import Rule, collect_rules, rule
from pants.engine.target import TransitiveTargets, TransitiveTargetsRequest
from pants.engine.unions import UnionRule
from pants.util.logging import LogLevel

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CCBinaryFieldSet(PackageFieldSet, RunFieldSet):
    required_fields = (CCDependenciesField,)

    dependencies: CCDependenciesField
    output_path: OutputPathField


@rule(level=LogLevel.DEBUG)
async def package_cc_binary(
    subsystem: CCSubsystem,
    toolchain: CCToolchain,
    field_set: CCBinaryFieldSet,
) -> BuiltPackage:
    # Grab all dependency targets for this binary (i.e. CCSourceTarget(s) + CCLibraryTarget(s))
    # TODO: Handle cc_library when it become availables, right now, sources are only allowable input
    transitive_targets = await Get(TransitiveTargets, TransitiveTargetsRequest([field_set.address]))

    # Create Field Sets from transitive source targets, in order to pass to compilation
    cc_field_sets = [CCFieldSet.create(target) for target in transitive_targets.dependencies]

    # TODO: Should this be Fallible, or just Compiled?
    compiled_objects = await MultiGet(
        Get(FallibleCompiledCCObject, CompileCCSourceRequest(cc_field_set))
        for cc_field_set in cc_field_sets
    )

    # Merge all individual compiled objects into a single digest
    digest = await Get(
        Digest, MergeDigests([obj.process_result.output_digest for obj in compiled_objects])
    )

    output_filename = PurePath(field_set.output_path.value_or_default(file_ending=None))
    binary = await Get(LinkedCCBinary, LinkCCBinaryRequest(digest, output_filename.name))

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
        UnionRule(PackageFieldSet, CCBinaryFieldSet),
        UnionRule(RunFieldSet, CCBinaryFieldSet),
    )
