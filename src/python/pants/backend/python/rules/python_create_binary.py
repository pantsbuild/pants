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
from pants.rules.core.determine_source_files import AllSourceFilesRequest, SourceFiles


@rule
async def create_python_binary(python_binary_adaptor: PythonBinaryAdaptor) -> CreatedBinary:
    # TODO(#8420) This way of calculating the entry point works but is a bit hackish.
    if hasattr(python_binary_adaptor, "entry_point"):
        entry_point = python_binary_adaptor.entry_point
    else:
        sources = await Get[SourceFiles](
            AllSourceFilesRequest([python_binary_adaptor], strip_source_roots=True)
        )
        # NB: `python_binary` targets may have 0-1 sources. This is enforced by
        # `PythonBinaryAdaptor`.
        if len(sources.snapshot.files) == 1:
            module_name = sources.snapshot.files[0]
            entry_point = PythonBinary.translate_source_path_to_py_module_specifier(module_name)
        else:
            entry_point = None

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
