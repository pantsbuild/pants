# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from pants.backend.python.subsystems.setuptools import PythonDistributionFieldSet
from pants.backend.python.util_rules.interpreter_constraints import InterpreterConstraints
from pants.backend.python.util_rules.pex import Pex, PexRequest, PexRequirements
from pants.backend.python.util_rules.pex import rules as pex_rules
from pants.build_graph.address import Address
from pants.core.goals.package import BuiltPackage, PackageFieldSet
from pants.engine.addresses import Addresses
from pants.engine.fs import Digest, MergeDigests
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import TransitiveTargets, TransitiveTargetsRequest
from pants.util.meta import frozen_after_init


@frozen_after_init
@dataclass(unsafe_hash=True)
class LocalDistsPexRequest:
    """Request to build the local dists from the dependency closure of a set of addresses."""

    addresses: Addresses
    interpreter_constraints: InterpreterConstraints

    def __init__(
        self,
        addresses: Iterable[Address],
        *,
        interpreter_constraints: InterpreterConstraints = InterpreterConstraints()
    ) -> None:
        self.addresses = Addresses(addresses)
        self.interpreter_constraints = interpreter_constraints


@dataclass(frozen=True)
class LocalDistsPex:
    """A PEX file containing locally-built dists.

    Can be consumed from another PEX, e.g., by adding to PEX_PATH.
    """

    pex: Pex


@rule(desc="Building local distributions")
async def build_local_dists(
    request: LocalDistsPexRequest,
) -> LocalDistsPex:

    transitive_targets = await Get(TransitiveTargets, TransitiveTargetsRequest(request.addresses))

    python_dist_field_sets = [
        PythonDistributionFieldSet.create(target)
        for target in transitive_targets.closure
        if PythonDistributionFieldSet.is_applicable(target)
    ]

    dists = await MultiGet(
        [Get(BuiltPackage, PackageFieldSet, field_set) for field_set in python_dist_field_sets]
    )
    dists_digest = await Get(Digest, MergeDigests([dist.digest for dist in dists]))
    dists_pex = await Get(
        Pex,
        PexRequest(
            output_filename="local_dists.pex",
            requirements=PexRequirements(
                [art.relpath for dist in dists for art in dist.artifacts if art.relpath]
            ),
            interpreter_constraints=request.interpreter_constraints,
            additional_inputs=dists_digest,
            internal_only=True,
        ),
    )
    return LocalDistsPex(dists_pex)


def rules():
    return (*collect_rules(), *pex_rules())
