# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass
from typing import Optional, Tuple

from pants.backend.python.rules.pex import PexPlatforms, TwoStepPex
from pants.backend.python.rules.pex_from_targets import (
    PexFromTargetsRequest,
    TwoStepPexFromTargetsRequest,
)
from pants.backend.python.rules.targets import (
    PexAlwaysWriteCache,
    PexEmitWarnings,
    PexIgnoreErrors,
    PexInheritPath,
    PexShebang,
    PexZipSafe,
    PythonBinarySources,
    PythonEntryPoint,
)
from pants.backend.python.rules.targets import PythonPlatforms as PythonPlatformsField
from pants.backend.python.targets.python_binary import PythonBinary
from pants.engine.addressable import Addresses
from pants.engine.rules import UnionRule, rule
from pants.engine.selectors import Get
from pants.rules.core.binary import BinaryConfiguration, CreatedBinary
from pants.rules.core.determine_source_files import AllSourceFilesRequest, SourceFiles


@dataclass(frozen=True)
class PythonBinaryConfiguration(BinaryConfiguration):
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

    def generate_additional_args(self) -> Tuple[str, ...]:
        args = []
        if self.always_write_cache.value is True:
            args.append("--always-write-cache")
        if self.emit_warnings.value is False:
            args.append("--no-emit-warnings")
        if self.ignore_errors.value is True:
            args.append("--ignore-errors")
        if self.inherit_path.value is not None:
            args.append(f"--inherit-path={self.inherit_path.value}")
        if self.shebang.value is not None:
            args.append(f"--python-shebang={self.shebang.value}")
        if self.zip_safe.value is False:
            args.append(f"--not-zip-safe")
        return tuple(args)


@rule
async def create_python_binary(config: PythonBinaryConfiguration) -> CreatedBinary:
    entry_point: Optional[str]
    if config.entry_point.value is not None:
        entry_point = config.entry_point.value
    else:
        source_files = await Get[SourceFiles](
            AllSourceFilesRequest([config.sources], strip_source_roots=True)
        )
        # NB: `PythonBinarySources` enforces that we have 0-1 sources.
        if len(source_files.files) == 1:
            module_name = source_files.files[0]
            entry_point = PythonBinary.translate_source_path_to_py_module_specifier(module_name)
        else:
            entry_point = None

    output_filename = f"{config.address.target_name}.pex"
    two_step_pex = await Get[TwoStepPex](
        TwoStepPexFromTargetsRequest(
            PexFromTargetsRequest(
                addresses=Addresses([config.address]),
                entry_point=entry_point,
                platforms=PexPlatforms.create_from_platforms_field(config.platforms),
                output_filename=output_filename,
                additional_args=config.generate_additional_args(),
                description=f"Building {output_filename}",
            )
        )
    )
    pex = two_step_pex.pex
    return CreatedBinary(digest=pex.directory_digest, binary_name=pex.output_filename)


def rules():
    return [create_python_binary, UnionRule(BinaryConfiguration, PythonBinaryConfiguration)]
