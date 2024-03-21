# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import itertools
import os.path
from dataclasses import dataclass
from operator import itemgetter

from pants.backend.python.subsystems.setup import PythonSetup
from pants.engine.internals.synthetic_targets import SyntheticAddressMaps, SyntheticTargetsRequest
from pants.engine.internals.target_adaptor import TargetAdaptor
from pants.engine.rules import collect_rules, rule
from pants.engine.unions import UnionRule


@dataclass(frozen=True)
class PythonSyntheticLockfileTargetsRequest(SyntheticTargetsRequest):
    """Register the type used to create synthetic targets for Python lockfiles.

    As the paths for all lockfiles are known up-front, we set the `path` field to
    `SyntheticTargetsRequest.SINGLE_REQUEST_FOR_ALL_TARGETS` so that we get a single request for all
    our synthetic targets rather than one request per directory.
    """

    path: str = SyntheticTargetsRequest.SINGLE_REQUEST_FOR_ALL_TARGETS


def synthetic_lockfile_target_name(resolve: str) -> str:
    return f"_{resolve}_lockfile"


@rule
async def python_lockfile_synthetic_targets(
    request: PythonSyntheticLockfileTargetsRequest,
    python_setup: PythonSetup,
) -> SyntheticAddressMaps:
    if not python_setup.enable_synthetic_lockfiles:
        return SyntheticAddressMaps()

    resolves = [
        (os.path.dirname(lockfile), os.path.basename(lockfile), name)
        for name, lockfile in python_setup.resolves.items()
    ]

    return SyntheticAddressMaps.for_targets_request(
        request,
        [
            (
                os.path.join(spec_path, "BUILD.python-lockfiles"),
                tuple(
                    TargetAdaptor(
                        "_lockfiles",
                        name=synthetic_lockfile_target_name(name),
                        sources=[lockfile],
                        __description_of_origin__=f"the [python].resolves option {name!r}",
                    )
                    for _, lockfile, name in lockfiles
                ),
            )
            for spec_path, lockfiles in itertools.groupby(sorted(resolves), key=itemgetter(0))
        ],
    )


def rules():
    return (
        *collect_rules(),
        UnionRule(SyntheticTargetsRequest, PythonSyntheticLockfileTargetsRequest),
    )
