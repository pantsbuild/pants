# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass
from pathlib import Path

from pants.base.build_root import BuildRoot
from pants.build_graph.address import Address
from pants.engine.addressable import BuildFileAddresses
from pants.engine.console import Console
from pants.engine.fs import Digest, DirectoriesToMerge, DirectoryToMaterialize, Workspace
from pants.engine.goal import Goal, LineOriented
from pants.engine.legacy.graph import HydratedTarget
from pants.engine.rules import console_rule, rule, union
from pants.engine.selectors import Get, MultiGet
from pants.fs.fs import is_child_of
from pants.option.options_bootstrapper import OptionsBootstrapper


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
async def create_binary(
    addresses: BuildFileAddresses,
    console: Console,
    workspace: Workspace,
    options: Binary.Options,
    options_bootstrapper: OptionsBootstrapper,
    build_root: BuildRoot
    ) -> Binary:
  with Binary.line_oriented(options, console) as print_stdout:
    global_options = options_bootstrapper.bootstrap_options.for_global_scope()
    pants_distdir = Path(global_options.pants_distdir)
    if not is_child_of(pants_distdir, build_root.pathlib_path):
      console.print_stderr(f"When set to an absolute path, `--pants-distdir` must be relative to the build root."
      "You set it to {pants_distdir}. Instead, use a relative path or an absolute path relative to the build root.")
      return Binary(exit_code=1)

    relative_distdir = pants_distdir.relative_to(build_root.pathlib_path) if pants_distdir.is_absolute() else pants_distdir
    print_stdout(f"Generating binaries in `./{relative_distdir}`")

    binaries = await MultiGet(Get[CreatedBinary](Address, address.to_address()) for address in addresses)
    merged_digest = await Get[Digest](
      DirectoriesToMerge(tuple(binary.digest for binary in binaries))
    )
    result = workspace.materialize_directory(
      DirectoryToMaterialize(merged_digest, path_prefix=str(relative_distdir))
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
