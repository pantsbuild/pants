# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass

from pants.build_graph.address import Address
from pants.engine.addressable import Addresses
from pants.engine.console import Console
from pants.engine.fs import Digest, DirectoriesToMerge, DirectoryToMaterialize, Workspace
from pants.engine.goal import Goal, GoalSubsystem, LineOriented
from pants.engine.legacy.graph import HydratedTarget
from pants.engine.objects import union
from pants.engine.rules import goal_rule, rule
from pants.engine.selectors import Get, MultiGet
from pants.rules.core.distdir import DistDir


@union
class BinaryTarget:
  pass


@union
@dataclass(frozen=True)
class CreatedBinary:
  digest: Digest
  binary_name: str


class BinaryOptions(LineOriented, GoalSubsystem):
  """Create a runnable binary."""

  name = "binary"

  required_union_implementations = (BinaryTarget,)


class Binary(Goal):
  subsystem_cls = BinaryOptions


@goal_rule
async def create_binary(
  addresses: Addresses,
  console: Console,
  workspace: Workspace,
  options: BinaryOptions,
  distdir: DistDir,
) -> Binary:
  with options.line_oriented(console) as print_stdout:
    print_stdout(f"Generating binaries in `./{distdir.relpath}`")
    binaries = await MultiGet(Get[CreatedBinary](Address, address) for address in addresses)
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
  return [create_binary, coordinator_of_binaries]
