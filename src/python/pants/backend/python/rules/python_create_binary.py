# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass
from typing import Optional

from pants.backend.python.rules.pex import Pex
from pants.backend.python.rules.pex_from_target_closure import CreatePexFromTargetClosure
from pants.backend.python.rules.targets import EntryPoint, PythonBinarySources
from pants.backend.python.targets.python_binary import PythonBinary
from pants.engine.addressable import Addresses
from pants.engine.rules import UnionRule, rule
from pants.engine.selectors import Get
from pants.engine.target import Target
from pants.rules.core.binary import BinaryImplementation, CreatedBinary
from pants.rules.core.determine_source_files import AllSourceFilesRequest, SourceFiles


@dataclass(frozen=True)
class PythonBinaryImplementation(BinaryImplementation):
    required_fields = (EntryPoint, PythonBinarySources)

    sources: PythonBinarySources
    entry_point: EntryPoint

    # TODO: consume the other PythonBinary fields like `ZipSafe` and `AlwaysWriteCache`. These are
    #  optional fields. If your target type has them registered, we can do extra meaningful things;
    #  if you don't have them on your target type, we can still operate so long as you have the
    #  required fields. Use `Target.get()` in the `create()` method.

    @classmethod
    def create(cls, tgt: Target) -> "PythonBinaryImplementation":
        return cls(
            address=tgt.address, sources=tgt[PythonBinarySources], entry_point=tgt[EntryPoint]
        )


@rule
async def create_python_binary(implementation: PythonBinaryImplementation) -> CreatedBinary:
    entry_point: Optional[str]
    if implementation.entry_point.value is not None:
        entry_point = implementation.entry_point.value
    else:
        source_files = await Get[SourceFiles](
            AllSourceFilesRequest([implementation.sources], strip_source_roots=True)
        )
        # NB: `PythonBinarySources` enforces that we have 0-1 sources.
        if len(source_files.files) == 1:
            module_name = source_files.files[0]
            entry_point = PythonBinary.translate_source_path_to_py_module_specifier(module_name)
        else:
            entry_point = None

    request = CreatePexFromTargetClosure(
        addresses=Addresses([implementation.address]),
        entry_point=entry_point,
        output_filename=f"{implementation.address.target_name}.pex",
    )

    pex = await Get[Pex](CreatePexFromTargetClosure, request)
    return CreatedBinary(digest=pex.directory_digest, binary_name=pex.output_filename)


def rules():
    return [create_python_binary, UnionRule(BinaryImplementation, PythonBinaryImplementation)]
