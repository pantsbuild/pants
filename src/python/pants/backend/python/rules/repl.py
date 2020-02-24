# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import logging
from dataclasses import dataclass
from typing import ClassVar

from pants.backend.python.rules.pex import Pex
from pants.backend.python.rules.pex_from_target_closure import CreatePexFromTargetClosure
from pants.backend.python.subsystems.ipython import IPython
from pants.engine.addressable import Addresses
from pants.engine.legacy.graph import TransitiveHydratedTargets
from pants.engine.legacy.structs import PythonTargetAdaptor
from pants.engine.rules import UnionRule, rule, subsystem_rule
from pants.engine.selectors import Get
from pants.rules.core.repl import ReplBinary, ReplImplementation

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PythonRepl:
    name: ClassVar[str] = "python"
    addresses: Addresses


@rule
async def run_python_repl(repl: PythonRepl) -> ReplBinary:
    targets = await Get[TransitiveHydratedTargets](Addresses, repl.addresses)
    python_addresses = Addresses(
        ht.address for ht in targets.closure if isinstance(ht.adaptor, PythonTargetAdaptor)
    )
    create_pex = CreatePexFromTargetClosure(
        addresses=python_addresses, output_filename="python-repl.pex",
    )

    repl_pex = await Get[Pex](CreatePexFromTargetClosure, create_pex)
    return ReplBinary(digest=repl_pex.directory_digest, binary_name=repl_pex.output_filename,)


@dataclass(frozen=True)
class IPythonRepl:
    name: ClassVar[str] = "ipython"
    addresses: Addresses


@rule
async def run_ipython_repl(repl: IPythonRepl, ipython: IPython) -> ReplBinary:
    targets = await Get[TransitiveHydratedTargets](Addresses, repl.addresses)
    python_addresses = Addresses(
        ht.address for ht in targets.closure if isinstance(ht.adaptor, PythonTargetAdaptor)
    )

    create_pex = CreatePexFromTargetClosure(
        addresses=python_addresses,
        output_filename="ipython-repl.pex",
        entry_point=ipython.get_entry_point(),
        additional_requirements=ipython.get_requirement_specs(),
    )

    repl_pex = await Get[Pex](CreatePexFromTargetClosure, create_pex)
    return ReplBinary(digest=repl_pex.directory_digest, binary_name=repl_pex.output_filename,)


def rules():
    return [
        subsystem_rule(IPython),
        UnionRule(ReplImplementation, PythonRepl),
        UnionRule(ReplImplementation, IPythonRepl),
        run_python_repl,
        run_ipython_repl,
    ]
