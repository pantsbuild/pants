# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
from dataclasses import dataclass
from typing import Tuple

from pants.backend.python.target_types import (
    PexAlwaysWriteCache,
    PexEmitWarnings,
    PexIgnoreErrors,
    PexInheritPath,
    PexShebang,
    PexZipSafe,
    PythonBinaryDefaults,
    PythonBinarySources,
    PythonEntryPoint,
)
from pants.backend.python.target_types import PythonPlatforms as PythonPlatformsField
from pants.backend.python.util_rules.pex import PexPlatforms, TwoStepPex
from pants.backend.python.util_rules.pex_from_targets import (
    PexFromTargetsRequest,
    TwoStepPexFromTargetsRequest,
)
from pants.core.goals.binary import BinaryFieldSet, CreatedBinary
from pants.core.goals.package import BuiltPackage, OutputPathField, PackageFieldSet
from pants.core.goals.run import RunFieldSet
from pants.engine.fs import PathGlobs, Paths
from pants.engine.rules import Get, collect_rules, rule
from pants.engine.target import InvalidFieldException
from pants.engine.unions import UnionRule
from pants.option.global_options import FilesNotFoundBehavior, GlobalOptions
from pants.source.source_root import SourceRoot, SourceRootRequest
from pants.util.logging import LogLevel


@dataclass(frozen=True)
class PythonBinaryFieldSet(PackageFieldSet, BinaryFieldSet, RunFieldSet):
    required_fields = (PythonEntryPoint, PythonBinarySources)

    sources: PythonBinarySources
    entry_point: PythonEntryPoint

    output_path: OutputPathField
    always_write_cache: PexAlwaysWriteCache
    emit_warnings: PexEmitWarnings
    ignore_errors: PexIgnoreErrors
    inherit_path: PexInheritPath
    shebang: PexShebang
    zip_safe: PexZipSafe
    platforms: PythonPlatformsField

    def generate_additional_args(
        self, python_binary_defaults: PythonBinaryDefaults
    ) -> Tuple[str, ...]:
        args = []
        if self.always_write_cache.value is True:
            args.append("--always-write-cache")
        if self.emit_warnings.value_or_global_default(python_binary_defaults) is False:
            args.append("--no-emit-warnings")
        if self.ignore_errors.value is True:
            args.append("--ignore-errors")
        if self.inherit_path.value is not None:
            args.append(f"--inherit-path={self.inherit_path.value}")
        if self.shebang.value is not None:
            args.append(f"--python-shebang={self.shebang.value}")
        if self.zip_safe.value is False:
            args.append("--not-zip-safe")
        return tuple(args)


@rule(level=LogLevel.DEBUG)
async def package_python_binary(
    field_set: PythonBinaryFieldSet,
    python_binary_defaults: PythonBinaryDefaults,
    global_options: GlobalOptions,
) -> BuiltPackage:
    entry_point = field_set.entry_point.value
    if entry_point is None:
        binary_source_paths = await Get(
            Paths, PathGlobs, field_set.sources.path_globs(FilesNotFoundBehavior.error)
        )
        if len(binary_source_paths.files) != 1:
            raise InvalidFieldException(
                "No `entry_point` was set for the target "
                f"{repr(field_set.address)}, so it must have exactly one source, but it has "
                f"{len(binary_source_paths.files)}"
            )
        entry_point_path = binary_source_paths.files[0]
        source_root = await Get(
            SourceRoot,
            SourceRootRequest,
            SourceRootRequest.for_file(entry_point_path),
        )
        entry_point = PythonBinarySources.translate_source_file_to_entry_point(
            os.path.relpath(entry_point_path, source_root.path)
        )

    output_filename = field_set.output_path.value_or_default(
        field_set.address,
        file_ending="pex",
        use_legacy_format=global_options.options.pants_distdir_legacy_paths,
    )
    two_step_pex = await Get(
        TwoStepPex,
        TwoStepPexFromTargetsRequest(
            PexFromTargetsRequest(
                addresses=[field_set.address],
                internal_only=False,
                entry_point=entry_point,
                platforms=PexPlatforms.create_from_platforms_field(field_set.platforms),
                output_filename=output_filename,
                additional_args=field_set.generate_additional_args(python_binary_defaults),
            )
        ),
    )
    return BuiltPackage(two_step_pex.pex.digest, relpath=output_filename)


@rule(level=LogLevel.DEBUG)
async def create_python_binary(field_set: PythonBinaryFieldSet) -> CreatedBinary:
    pex = await Get(BuiltPackage, PackageFieldSet, field_set)
    return CreatedBinary(pex.digest, pex.relpath)


def rules():
    return [
        *collect_rules(),
        UnionRule(PackageFieldSet, PythonBinaryFieldSet),
        UnionRule(BinaryFieldSet, PythonBinaryFieldSet),
    ]
