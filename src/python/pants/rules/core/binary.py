# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass

from pants.build_graph.address import Address
from pants.engine.addressable import BuildFileAddresses
from pants.engine.console import Console
from pants.engine.fs import Digest, DirectoriesToMerge, DirectoryToMaterialize, Workspace
from pants.engine.goal import Goal, GoalSubsystem, LineOriented
from pants.engine.legacy.graph import HydratedTarget
from pants.engine.rules import console_rule, rule, union
from pants.engine.selectors import Get, MultiGet
from pants.rules.core.distdir import DistDir


class BinaryOptions(LineOriented, GoalSubsystem):
  """Create a runnable binary."""
  name = 'binary'


class Binary(Goal):
  subsystem_cls = BinaryOptions


@union
class BinaryTarget:
  pass


@union
@dataclass(frozen=True)
class CreatedBinary:
  digest: Digest
  binary_name: str


@console_rule
async def create_binary(
    addresses: BuildFileAddresses,
    console: Console,
    workspace: Workspace,
    options: BinaryOptions,
    distdir: DistDir,
    ) -> Binary:
  with options.line_oriented(console) as print_stdout:
    print_stdout(f"Generating binaries in `./{distdir.relpath}`")
    binaries = await MultiGet(Get[CreatedBinary](Address, address.to_address()) for address in addresses)
    merged_digest = await Get[Digest](
      DirectoriesToMerge(tuple(binary.digest for binary in binaries))
    )
    result = workspace.materialize_directory(
      DirectoryToMaterialize(merged_digest, path_prefix=str(distdir.relpath))
    )
    for path in result.output_paths:
      print_stdout(f"Wrote {path}")
  return Binary(exit_code=0)


@rule
async def coordinator_of_binaries(target: HydratedTarget) -> CreatedBinary:
  binary = await Get[CreatedBinary](BinaryTarget, target.adaptor)
  return binary


def rules():
  return [
    create_binary,
    coordinator_of_binaries,
  ]
