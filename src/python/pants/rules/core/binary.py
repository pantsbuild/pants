# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass
from typing import Any

from pants.backend.python.rules.pex import Pex
from pants.build_graph.address import Address
from pants.engine.addressable import BuildFileAddresses
from pants.engine.console import Console
from pants.engine.fs import Digest, DirectoryToMaterialize, Workspace
from pants.engine.goal import Goal, LineOriented
from pants.engine.legacy.graph import HydratedTarget
from pants.engine.legacy.structs import PythonBinaryAdaptor
from pants.engine.rules import console_rule, optionable_rule, rule, union
from pants.engine.selectors import Get


@dataclass(frozen=True)
class Binary(LineOriented, Goal):
  name = 'binary'


@union
class BinaryTarget:
  pass


@union
@dataclass(frozen=True)
class CreatedBinary:
  digest: Digest


@console_rule
def create_binary(addresses: BuildFileAddresses, console: Console, workspace: Workspace, options: Binary.Options) -> Binary:
  with Binary.line_oriented(options, console) as (print_stdout, print_stderr):
    print_stdout("Generating binaries in `dist/`")
    binaries = yield [Get(CreatedBinary, Address, address.to_address()) for address in addresses]
    for binary in binaries:
      dtm = DirectoryToMaterialize(
        path = 'dist/',
        directory_digest = binary.digest,
      )
      output = workspace.materialize_directories((dtm,))
      for path in output.dependencies[0].output_paths:
        print_stdout(f"Wrote {path}")

  yield Binary(exit_code=0)


@rule
def coordinator_of_binaries(target: HydratedTarget) -> CreatedBinary:
  binary = yield Get(CreatedBinary, BinaryTarget, target.adaptor)
  yield binary


def rules():
  return [
    create_binary,
    coordinator_of_binaries,
  ]
