# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

from dataclasses import dataclass

from pants.build_graph.build_configuration import BuildConfiguration
from pants.engine.internals.synthetic_targets import SyntheticAddressMaps, SyntheticTargetsRequest
from pants.engine.internals.target_adaptor import TargetAdaptor
from pants.engine.rules import collect_rules, rule
from pants.engine.unions import UnionRule


@dataclass(frozen=True)
class SyntheticSubsystemTargetsRequest(SyntheticTargetsRequest):
    """Register the type used to create synthetic targets for all subsystems.

    As the paths for all subsystems are known up-front, we set the `path` field to
    `SyntheticTargetsRequest.SINGLE_REQUEST_FOR_ALL_TARGETS` so that we get a single request for all
    our synthetic targets rather than one request per directory.
    """

    path: str = SyntheticTargetsRequest.SINGLE_REQUEST_FOR_ALL_TARGETS


@rule
async def get_synthetic_subsystem_targets(
    request: SyntheticSubsystemTargetsRequest,
    build_configuration: BuildConfiguration,
) -> SyntheticAddressMaps:
    return SyntheticAddressMaps.for_targets_request(
        request,
        [
            (
                "BUILD.subsystems",
                tuple(
                    TargetAdaptor(
                        "_subsystem",
                        name=f"subsystem-{subsystem.options_scope}",
                        description=subsystem.help,
                    )
                    for subsystem in build_configuration.all_subsystems
                    if subsystem.options_scope and not subsystem.options_scope.startswith("_")
                ),
            )
        ],
    )


def rules():
    return (
        *collect_rules(),
        UnionRule(SyntheticTargetsRequest, SyntheticSubsystemTargetsRequest),
    )
