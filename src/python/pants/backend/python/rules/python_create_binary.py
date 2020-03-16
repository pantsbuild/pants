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
from pants.engine.target import SourcesRequest, SourcesResult, Target, hydrated_struct_to_target
from pants.rules.core.binary import BinaryTarget, CreatedBinary
from pants.rules.core.strip_source_roots import SourceRootStrippedSources, StripSnapshotRequest


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
async def create_python_binary(python_binary_adaptor: PythonBinaryAdaptor) -> CreatedBinary:
    # TODO: instead, get this to work via the engine. Have the rule request `PythonBinaryFields`,
    #  which means that all we care about in the world is that those 2 Fields are defined on the
    #  target (so it's extensible to custom target types).
    hydrated_struct = await Get[HydratedStruct](Address, python_binary_adaptor.address)
    tgt = hydrated_struct_to_target(hydrated_struct, target_types=python_targets())
    fields = PythonBinaryFields.create(tgt)

    entry_point: Optional[str]
    if fields.entry_point.value is not None:
        entry_point = fields.entry_point.value
    else:
        # TODO: rework determine_source_files.py to work with the Target API. It should take the
        #  Sources AsyncField as input, rather than TargetAdaptor.
        sources_result = await Get[SourcesResult](SourcesRequest, fields.sources.request)
        stripped_sources = await Get[SourceRootStrippedSources](
            StripSnapshotRequest(sources_result.snapshot)
        )
        source_files = stripped_sources.snapshot.files
        # NB: `PythonBinarySources` enforces that we have 0-1 sources.
        if len(source_files) == 1:
            module_name = source_files[0]
            entry_point = PythonBinary.translate_source_path_to_py_module_specifier(module_name)
        else:
            entry_point = None

    request = CreatePexFromTargetClosure(
        # TODO: pass Targets, rather than Addresses, to this helper.
        addresses=Addresses([tgt.address]),
        entry_point=entry_point,
        output_filename=f"{tgt.address.target_name}.pex",
    )

    pex = await Get[Pex](CreatePexFromTargetClosure, request)
    return CreatedBinary(digest=pex.directory_digest, binary_name=pex.output_filename)


def rules():
    return [
        UnionRule(BinaryTarget, PythonBinaryAdaptor),
        create_python_binary,
    ]
