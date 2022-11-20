# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import collections
import json
from dataclasses import asdict, dataclass, is_dataclass
from typing import Any, Iterable

from pants.engine.collection import Collection
from pants.engine.console import Console
from pants.engine.goal import Goal, GoalSubsystem, Outputting
from pants.engine.rules import Get, MultiGet, collect_rules, goal_rule, rule
from pants.engine.target import (
    Dependencies,
    DependenciesRequest,
    Field,
    HydratedSources,
    HydrateSourcesRequest,
    SourcesField,
    Target,
    Targets,
    UnexpandedTargets,
)
from pants.option.option_types import BoolOption


class PeekSubsystem(Outputting, GoalSubsystem):
    """Display detailed target information in JSON form."""

    name = "peek"
    help = "Display BUILD target info"

    exclude_defaults = BoolOption(
        default=False,
        help="Whether to leave off values that match the target-defined default values.",
    )


class Peek(Goal):
    subsystem_cls = PeekSubsystem
    environment_behavior = Goal.EnvironmentBehavior.LOCAL_ONLY


def _normalize_value(val: Any) -> Any:
    if isinstance(val, collections.abc.Mapping):
        return {str(k): _normalize_value(v) for k, v in val.items()}
    return val


@dataclass(frozen=True)
class TargetData:
    target: Target
    # Sources may not be registered on the target, so we'll have nothing to expand.
    expanded_sources: tuple[str, ...] | None
    expanded_dependencies: tuple[str, ...]

    def to_dict(self, exclude_defaults: bool = False) -> dict:
        nothing = object()
        fields = {
            (
                f"{k.alias}_raw" if issubclass(k, (SourcesField, Dependencies)) else k.alias
            ): _normalize_value(v.value)
            for k, v in self.target.field_values.items()
            if not (exclude_defaults and getattr(k, "default", nothing) == v.value)
        }

        fields["dependencies"] = self.expanded_dependencies
        if self.expanded_sources is not None:
            fields["sources"] = self.expanded_sources

        return {
            "address": self.target.address.spec,
            "target_type": self.target.alias,
            **dict(sorted(fields.items())),
        }


class TargetDatas(Collection[TargetData]):
    pass


def render_json(tds: Iterable[TargetData], exclude_defaults: bool = False) -> str:
    return f"{json.dumps([td.to_dict(exclude_defaults) for td in tds], indent=2, cls=_PeekJsonEncoder)}\n"


class _PeekJsonEncoder(json.JSONEncoder):
    """Allow us to serialize some commmonly found types in BUILD files."""

    def default(self, o):
        """Return a serializable object for o."""
        if isinstance(o, str):  # early exit prevents strings from being treated as sequences
            return o
        if o is None:
            return o
        if is_dataclass(o):
            return asdict(o)
        if isinstance(o, collections.abc.Mapping):
            return dict(o)
        if (
            isinstance(o, collections.abc.Sequence)
            or isinstance(o, set)
            or isinstance(o, collections.abc.Set)
        ):
            return list(o)
        if isinstance(o, Field):
            return self.default(o.value)
        try:
            return super().default(o)
        except TypeError:
            return str(o)


@rule
async def get_target_data(
    # NB: We must preserve target generators, not replace with their generated targets.
    targets: UnexpandedTargets,
) -> TargetDatas:
    sorted_targets = sorted(targets, key=lambda tgt: tgt.address)

    # We "hydrate" sources fields with the engine, but not every target has them registered.
    targets_with_sources = []
    for tgt in sorted_targets:
        if tgt.has_field(SourcesField):
            targets_with_sources.append(tgt)

    # NB: When determining dependencies, we replace target generators with their generated targets.
    dependencies_per_target = await MultiGet(
        Get(
            Targets,
            DependenciesRequest(tgt.get(Dependencies), include_special_cased_deps=True),
        )
        for tgt in sorted_targets
    )
    hydrated_sources_per_target = await MultiGet(
        Get(HydratedSources, HydrateSourcesRequest(tgt[SourcesField]))
        for tgt in targets_with_sources
    )

    expanded_dependencies = [
        tuple(dep.address.spec for dep in deps)
        for tgt, deps in zip(sorted_targets, dependencies_per_target)
    ]
    expanded_sources_map = {
        tgt.address: hs.snapshot.files
        for tgt, hs in zip(targets_with_sources, hydrated_sources_per_target)
    }

    return TargetDatas(
        TargetData(
            tgt,
            expanded_dependencies=expanded_deps,
            expanded_sources=expanded_sources_map.get(tgt.address),
        )
        for tgt, expanded_deps in zip(sorted_targets, expanded_dependencies)
    )


@goal_rule
async def peek(
    console: Console,
    subsys: PeekSubsystem,
    targets: UnexpandedTargets,
) -> Peek:
    tds = await Get(TargetDatas, UnexpandedTargets, targets)
    output = render_json(tds, subsys.exclude_defaults)
    with subsys.output(console) as write_stdout:
        write_stdout(output)
    return Peek(exit_code=0)


def rules():
    return collect_rules()
