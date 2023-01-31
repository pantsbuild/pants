# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from pants.backend.python.framework.stevedore.target_types import (
    ResolvedStevedoreEntryPoints,
    ResolveStevedoreEntryPointsRequest,
    StevedoreEntryPoints,
    StevedoreEntryPointsField,
    StevedoreNamespaceField,
)
from pants.backend.python.goals.setup_py import SetupKwargsRequest
from pants.base.specs import DirGlobSpec, RawSpecs
from pants.engine.addresses import Address
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import Targets
from pants.util.frozendict import FrozenDict
from pants.util.logging import LogLevel


@dataclass(frozen=True)
class StevedoreSetupKwargs:
    """
    kwargs = {"entry_points": {"stevedore.extension.namespace": ("entry = p.o.i.n:t")}
    """

    kwargs: FrozenDict[str, FrozenDict[str, tuple[str, ...]]]


@dataclass(frozen=True)
class StevedoreSetupKwargsRequest:
    """Light wrapper around SetupKwargsRequest to allow composed Kwargs."""

    request: SetupKwargsRequest


@rule(
    desc="Prepare stevedore_extension kwargs (entry_points) for usage in setup.py.",
    level=LogLevel.DEBUG,
)
async def stevedore_kwargs_for_setup_py(
    stevedore_request: StevedoreSetupKwargsRequest,
) -> StevedoreSetupKwargs:
    """Generate the StevedoreExtension entry_points args for use in SetupKwargs.

    Only one plugin can provide Kwargs for a given setup, so that repo-specific plugin's setup_py
    rule should do something like this:

    custom_args = {...}
    stevedore_kwargs = await Get(StevedoreSetupKwargs, StevedoreSetupKwargsRequest(request))
    return SetupKwargs(
        **request.explicit_kwargs,
        **stevedore_kwargs.kwargs,
        **custom_args,
        address=address
    )
    """

    request: SetupKwargsRequest = stevedore_request.request
    address: Address = request.target.address

    sibling_targets = await Get(
        Targets,
        RawSpecs(
            dir_globs=(DirGlobSpec(address.spec_path),),
            description_of_origin="stevedore_kwargs_for_setup_py",
        ),
    )
    stevedore_targets = [tgt for tgt in sibling_targets if tgt.has_field(StevedoreEntryPointsField)]
    resolved_entry_points: tuple[ResolvedStevedoreEntryPoints, ...] = await MultiGet(
        Get(
            ResolvedStevedoreEntryPoints,
            ResolveStevedoreEntryPointsRequest(tgt[StevedoreEntryPointsField]),
        )
        for tgt in stevedore_targets
    )

    entry_points_kwargs = defaultdict(list)
    for target, resolved_ep in zip(stevedore_targets, resolved_entry_points):
        namespace: StevedoreNamespaceField = target[StevedoreNamespaceField]
        entry_points: StevedoreEntryPoints | None = resolved_ep.val
        if entry_points is None:
            continue

        for entry_point in entry_points:
            entry_points_kwargs[str(namespace.value)].append(
                f"{entry_point.name} = {entry_point.value.spec}"
            )
    return StevedoreSetupKwargs(
        FrozenDict(
            {
                "entry_points": FrozenDict(
                    (k, tuple(sorted(v))) for k, v in sorted(entry_points_kwargs.items())
                )
            }
        )
    )


def rules():
    return collect_rules()
