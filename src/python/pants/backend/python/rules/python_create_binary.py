# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.python.rules.pex import Pex
from pants.backend.python.rules.pex_from_target_closure import CreatePexFromTargetClosure
from pants.backend.python.targets.python_binary import PythonBinary
from pants.engine.addressable import Addresses
from pants.engine.legacy.structs import PythonBinaryAdaptor
from pants.engine.rules import UnionRule, rule
from pants.engine.selectors import Get
from pants.rules.core.binary import BinaryTarget, CreatedBinary
from pants.rules.core.strip_source_roots import SourceRootStrippedSources, StripTargetRequest


@rule
async def create_python_binary(python_binary_adaptor: PythonBinaryAdaptor) -> CreatedBinary:
    # TODO(#8420) This way of calculating the entry point works but is a bit hackish.
    if hasattr(python_binary_adaptor, "entry_point"):
        entry_point = python_binary_adaptor.entry_point
    else:
        sources_snapshot = python_binary_adaptor.sources.snapshot
        # NB: A `python_binary` may have either 0 or 1 source files. This is validated by
        # `PythonBinaryAdaptor`.
        if not sources_snapshot.files:
            entry_point = None
        else:
            output = await Get[SourceRootStrippedSources](StripTargetRequest(python_binary_adaptor))
            module_name = output.snapshot.files[0]
            entry_point = PythonBinary.translate_source_path_to_py_module_specifier(module_name)

    request = CreatePexFromTargetClosure(
        addresses=Addresses((python_binary_adaptor.address,)),
        entry_point=entry_point,
        output_filename=f"{python_binary_adaptor.address.target_name}.pex",
    )

    pex = await Get[Pex](CreatePexFromTargetClosure, request)
    return CreatedBinary(digest=pex.directory_digest, binary_name=pex.output_filename)


def rules():
    return [
        UnionRule(BinaryTarget, PythonBinaryAdaptor),
        create_python_binary,
    ]
