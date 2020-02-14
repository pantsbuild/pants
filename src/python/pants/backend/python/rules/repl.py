# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import logging
from dataclasses import dataclass

from pants.backend.python.rules.pex import Pex
from pants.backend.python.rules.pex_from_target_closure import CreatePexFromTargetClosure
from pants.engine.addressable import Addresses
from pants.engine.legacy.graph import TransitiveHydratedTargets
from pants.engine.legacy.structs import PythonTargetAdaptor
from pants.engine.rules import UnionRule, rule
from pants.engine.selectors import Get
from pants.rules.core.repl import ReplBinary, ReplImplementation


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PythonRepl:
  addresses: Addresses


@rule
async def targets_to_python_repl(addresses: Addresses) -> PythonRepl:
  return PythonRepl(addresses=addresses)


@rule
async def run_python_repl(repl: PythonRepl) -> ReplBinary:
  targets = await Get[TransitiveHydratedTargets](Addresses, repl.addresses)
  python_addresses = Addresses(
    ht.address for ht in targets.closure if isinstance(ht.adaptor, PythonTargetAdaptor)
  )
  create_pex = CreatePexFromTargetClosure(
    addresses=python_addresses,
    output_filename="python-repl.pex",
  )

  repl_pex = await Get[Pex](CreatePexFromTargetClosure, create_pex)
  return ReplBinary(
    digest=repl_pex.directory_digest,
    binary_name=repl_pex.output_filename,
  )


def rules():
  return [
    UnionRule(ReplImplementation, PythonRepl),
    run_python_repl,
    targets_to_python_repl,
  ]
