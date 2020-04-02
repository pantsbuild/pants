# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass
from typing import Optional, Tuple

from pants.backend.python.rules.pex import Pex
from pants.backend.python.rules.pex_from_target_closure import CreatePexFromTargetClosure
from pants.backend.python.rules.targets import (
    PexAlwaysWriteCache,
    PexEmitWarnings,
    PexIgnoreErrors,
    PexIndexes,
    PexInheritPath,
    PexRepositories,
    PexShebang,
    PexZipSafe,
    PythonBinarySources,
    PythonEntryPoint,
    PythonPlatforms,
)
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
    indexes: PexIndexes
    inherit_path: PexInheritPath
    repositories: PexRepositories
    shebang: PexShebang
    zip_safe: PexZipSafe
    platforms: PythonPlatforms

    def generate_additional_args(self) -> Tuple[str, ...]:
        args = []
        if self.always_write_cache.value is True:
            args.append("--always-write-cache")
        if self.emit_warnings.value is False:
            args.append("--no-emit-warnings")
        if self.ignore_errors.value is True:
            args.append("--ignore-errors")
        if self.indexes.value is not None:
            if not self.indexes.value:
                args.append("--no-index")
            else:
                args.extend([f"--index={index}" for index in self.indexes.value])
        if self.inherit_path.value is not None:
            args.append(f"--inherit-path={self.inherit_path.value}")
        if self.repositories.value is not None:
            args.extend([f"--repo={repo}" for repo in self.repositories.value])
        if self.shebang.value is not None:
            args.append(f"--python-shebang={self.shebang.value}")
        if self.platforms.value is not None:
            args.extend([f"--platform={platform}" for platform in self.platforms.value])
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

    request = CreatePexFromTargetClosure(
        addresses=Addresses([config.address]),
        entry_point=entry_point,
        output_filename=f"{config.address.target_name}.pex",
        additional_args=config.generate_additional_args(),
    )

    pex = await Get[Pex](CreatePexFromTargetClosure, request)
    return CreatedBinary(digest=pex.directory_digest, binary_name=pex.output_filename)


def rules():
    return [create_python_binary, UnionRule(BinaryConfiguration, PythonBinaryConfiguration)]
