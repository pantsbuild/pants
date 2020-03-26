# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass
from typing import Optional, cast

from pants.backend.python.rules.ipex import IpexRequest, IpexResult
from pants.backend.python.rules.pex import CreatePex, Pex
from pants.backend.python.rules.pex_from_target_closure import CreatePexFromTargetClosure
from pants.backend.python.rules.targets import EntryPoint, PythonBinarySources
from pants.backend.python.targets.python_binary import PythonBinary
from pants.build_graph.address import Address
from pants.engine.addressable import Addresses
from pants.engine.rules import UnionRule, rule, subsystem_rule
from pants.engine.selectors import Get
from pants.engine.target import Target
from pants.rules.core.binary import BinaryImplementation, CreatedBinary
from pants.rules.core.determine_source_files import AllSourceFilesRequest, SourceFiles
from pants.subsystem.subsystem import Subsystem


@dataclass(frozen=True)
class PythonBinaryImplementation(BinaryImplementation):
    required_fields = (EntryPoint, PythonBinarySources)

    address: Address
    sources: PythonBinarySources
    entry_point: EntryPoint

    # TODO: consume the other PythonBinary fields like `ZipSafe` and `AlwaysWriteCache`. These are
    #  optional fields. If your target type has them registered, we can do extra meaningful things;
    #  if you don't have them on your target type, we can still operate so long as you have the
    #  required fields. Use `Target.get()` in the `create()` method.

    @classmethod
    def create(cls, tgt: Target) -> "PythonBinaryImplementation":
        return cls(tgt.address, sources=tgt[PythonBinarySources], entry_point=tgt[EntryPoint])


class PexCreationOptions(Subsystem):
    options_scope = 'pex-creation'

    @classmethod
    def register_options(cls, register):
        super().register_options(register)
        register('--generate-ipex', type=bool, default=False, fingerprint=True,
                 help='Whether to generate a .ipex file, which will "hydrate" its dependencies '
                      'when it is executed, rather than at build time (the normal pex behavior). '
                      'This option can reduce the size of a shipped pex file by over 100x for '
                      'common deps such as tensorflow, but it does require access to a pypi-esque '
                      'index when executed.')

    @property
    def generate_ipex(self) -> bool:
        return cast(bool, self.get_options().generate_ipex)


@rule
async def create_python_binary(
    options: PexCreationOptions,
    implementation: PythonBinaryImplementation,
) -> CreatedBinary:
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

    request = await Get[CreatePex](CreatePexFromTargetClosure(
        addresses=Addresses([implementation.address]),
        entry_point=entry_point,
        output_filename=f"{implementation.address.target_name}.pex",
    ))
    if options.generate_ipex:
        request = ((await Get[IpexResult](IpexRequest(request)))
                   .underlying_request)

    pex = await Get[Pex](CreatePex, request)
    return CreatedBinary(digest=pex.directory_digest, binary_name=pex.output_filename)


def rules():
    return [
        subsystem_rule(PexCreationOptions),
        create_python_binary,
        UnionRule(BinaryImplementation, PythonBinaryImplementation),
    ]
