# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.python.rules.pex import TwoStepPex
from pants.backend.python.rules.pex_from_targets import (
    PexFromTargetsRequest,
    TwoStepPexFromTargetsRequest,
)
from pants.backend.python.subsystems.ipython import IPython
from pants.backend.python.target_types import PythonSources
from pants.core.goals.repl import ReplBinary, ReplImplementation
from pants.engine.addresses import Addresses
from pants.engine.rules import SubsystemRule, rule
from pants.engine.selectors import Get
from pants.engine.unions import UnionRule


class PythonRepl(ReplImplementation):
    name = "python"
    required_fields = (PythonSources,)


@rule
async def run_python_repl(repl: PythonRepl) -> ReplBinary:
    addresses = Addresses(tgt.address for tgt in repl.targets)
    two_step_pex = await Get[TwoStepPex](
        TwoStepPexFromTargetsRequest(
            PexFromTargetsRequest(addresses=addresses, output_filename="python-repl.pex",)
        )
    )
    repl_pex = two_step_pex.pex
    return ReplBinary(digest=repl_pex.digest, binary_name=repl_pex.output_filename)


class IPythonRepl(ReplImplementation):
    name = "ipython"
    required_fields = (PythonSources,)


@rule
async def run_ipython_repl(repl: IPythonRepl, ipython: IPython) -> ReplBinary:
    addresses = Addresses(tgt.address for tgt in repl.targets)
    two_step_pex = await Get[TwoStepPex](
        TwoStepPexFromTargetsRequest(
            PexFromTargetsRequest(
                addresses=addresses,
                output_filename="ipython-repl.pex",
                entry_point=ipython.get_entry_point(),
                additional_requirements=ipython.get_requirement_specs(),
            )
        )
    )
    repl_pex = two_step_pex.pex
    return ReplBinary(digest=repl_pex.digest, binary_name=repl_pex.output_filename)


def rules():
    return [
        SubsystemRule(IPython),
        UnionRule(ReplImplementation, PythonRepl),
        UnionRule(ReplImplementation, IPythonRepl),
        run_python_repl,
        run_ipython_repl,
    ]
