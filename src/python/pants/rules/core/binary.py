# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass

from pants.build_graph.address import Address
from pants.engine.addressable import BuildFileAddresses
from pants.engine.console import Console
from pants.engine.fs import Digest, DirectoryToMaterialize, Workspace
from pants.engine.goal import Goal, LineOriented
from pants.engine.legacy.graph import HydratedTarget
from pants.engine.rules import console_rule, rule, union
from pants.engine.selectors import Get, MultiGet


@dataclass(frozen=True)
class Binary(LineOriented, Goal):
  """Create a runnable binary."""
  name = 'binary'


@union
class BinaryTarget:
  pass


@union
@dataclass(frozen=True)
class CreatedBinary:
  digest: Digest
  binary_name: str


@console_rule
async def create_binary(addresses: BuildFileAddresses, console: Console, workspace: Workspace, options: Binary.Options) -> Binary:
  with Binary.line_oriented(options, console) as print_stdout:
    print_stdout("Generating binaries in `dist/`")
    binaries = await MultiGet(Get(CreatedBinary, Address, address.to_address()) for address in addresses)
    dirs_to_materialize = tuple(
      DirectoryToMaterialize(binary.digest, path_prefix='dist/') for binary in binaries
    )
    results = workspace.materialize_directories(dirs_to_materialize)
    for result in results.dependencies:
      for path in result.output_paths:
        print_stdout(f"Wrote {path}")
  return Binary(exit_code=0)


@rule
async def coordinator_of_binaries(target: HydratedTarget) -> CreatedBinary:
  binary = await Get(CreatedBinary, BinaryTarget, target.adaptor)
  return binary


def rules():
  return [
    create_binary,
    coordinator_of_binaries,
  ]
