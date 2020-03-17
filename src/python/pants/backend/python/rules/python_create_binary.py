# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass
from typing import Optional

from pants.backend.python.rules.pex import Pex
from pants.backend.python.rules.pex_from_target_closure import CreatePexFromTargetClosure
from pants.backend.python.rules.targets import EntryPoint, PythonBinarySources
from pants.backend.python.rules.targets import targets as python_targets
from pants.backend.python.targets.python_binary import PythonBinary
from pants.build_graph.address import Address
from pants.engine.addressable import Addresses
from pants.engine.legacy.structs import PythonBinaryAdaptor
from pants.engine.parser import HydratedStruct
from pants.engine.rules import UnionRule, rule
from pants.engine.selectors import Get
from pants.engine.target import Target, hydrated_struct_to_target
from pants.rules.core.binary import BinaryTarget, CreatedBinary
from pants.rules.core.strip_source_roots import SourceRootStrippedSources, StripSourcesFieldRequest


# TODO: consider replacing this with sugar like `SelectFields(EntryPoint, PythonBinarySources)` so
#  that the rule would request that instead of this dataclass. Note that this syntax must support
#  both optional_fields (see the below TODO) and opt-out `SentinelField`s
#  (see https://github.com/pantsbuild/pants/pull/9316#issuecomment-600152573).
@dataclass(frozen=True)
class PythonBinaryFields:
    address: Address
    sources: PythonBinarySources
    entry_point: EntryPoint

    # TODO: consume the other PythonBinary fields like `ZipSafe`. Consider making those fields
    #  optional. We _need_ PythonBinarySources and EntryPoint to work properly. If your target
    #  type also has ZipSafe, AlwaysWriteCache, etc, then we can do some additional things as an
    #  extra bonus. Consider adding `Target.maybe_get()` to facilitate this.

    @staticmethod
    def is_valid_target(tgt: Target) -> bool:
        return tgt.has_fields([EntryPoint, PythonBinarySources])

    @classmethod
    def create(cls, tgt: Target) -> "PythonBinaryFields":
        return cls(
            tgt.address, sources=tgt.get(PythonBinarySources), entry_point=tgt.get(EntryPoint)
        )


@rule
async def convert_python_binary_target(adaptor: PythonBinaryAdaptor) -> PythonBinaryFields:
    hydrated_struct = await Get[HydratedStruct](Address, adaptor.address)
    tgt = hydrated_struct_to_target(hydrated_struct, target_types=python_targets())
    return PythonBinaryFields.create(tgt)


@rule
async def create_python_binary(fields: PythonBinaryFields) -> CreatedBinary:
    entry_point: Optional[str]
    if fields.entry_point.value is not None:
        entry_point = fields.entry_point.value
    else:
        stripped_sources = await Get[SourceRootStrippedSources](
            StripSourcesFieldRequest(fields.sources)
        )
        source_files = stripped_sources.snapshot.files
        # NB: `PythonBinarySources` enforces that we have 0-1 sources.
        if len(source_files) == 1:
            module_name = source_files[0]
            entry_point = PythonBinary.translate_source_path_to_py_module_specifier(module_name)
        else:
            entry_point = None

    request = CreatePexFromTargetClosure(
        addresses=Addresses([fields.address]),
        entry_point=entry_point,
        output_filename=f"{fields.address.target_name}.pex",
    )

    pex = await Get[Pex](CreatePexFromTargetClosure, request)
    return CreatedBinary(digest=pex.directory_digest, binary_name=pex.output_filename)


def rules():
    return [
        UnionRule(BinaryTarget, PythonBinaryAdaptor),
        convert_python_binary_target,
        create_python_binary,
    ]
