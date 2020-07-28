# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass
from typing import Tuple

from pants.backend.python.rules.pex import PexPlatforms, TwoStepPex
from pants.backend.python.rules.pex_from_targets import (
    PexFromTargetsRequest,
    TwoStepPexFromTargetsRequest,
)
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
from pants.core.goals.binary import BinaryFieldSet, CreatedBinary
from pants.core.util_rules.determine_source_files import AllSourceFilesRequest, SourceFiles
from pants.engine.rules import Get, collect_rules, rule
from pants.engine.unions import UnionRule


@dataclass(frozen=True)
class PythonBinaryFieldSet(BinaryFieldSet):
    required_fields = (PythonEntryPoint, PythonBinarySources)

    sources: PythonBinarySources
    entry_point: PythonEntryPoint

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


@rule
async def create_python_binary(
    field_set: PythonBinaryFieldSet, python_binary_defaults: PythonBinaryDefaults
) -> CreatedBinary:
    entry_point = field_set.entry_point.value
    if entry_point is None:
        source_files = await Get(
            SourceFiles, AllSourceFilesRequest([field_set.sources], strip_source_roots=True)
        )
        entry_point = PythonBinarySources.translate_source_file_to_entry_point(source_files.files)

    output_filename = f"{field_set.address.target_name}.pex"
    two_step_pex = await Get(
        TwoStepPex,
        TwoStepPexFromTargetsRequest(
            PexFromTargetsRequest(
                addresses=[field_set.address],
                entry_point=entry_point,
                platforms=PexPlatforms.create_from_platforms_field(field_set.platforms),
                output_filename=output_filename,
                additional_args=field_set.generate_additional_args(python_binary_defaults),
            )
        ),
    )
    pex = two_step_pex.pex
    return CreatedBinary(digest=pex.digest, binary_name=pex.output_filename)


def rules():
    return [
        *collect_rules(),
        UnionRule(BinaryFieldSet, PythonBinaryFieldSet),
    ]
