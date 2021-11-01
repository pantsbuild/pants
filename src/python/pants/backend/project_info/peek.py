# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import collections
import json
from dataclasses import asdict, dataclass, is_dataclass
from typing import Any, Iterable, cast

from pants.engine.collection import Collection
from pants.engine.console import Console
from pants.engine.goal import Goal, GoalSubsystem, Outputting
from pants.engine.rules import Get, MultiGet, collect_rules, goal_rule, rule
from pants.engine.target import (
    Dependencies,
    DependenciesRequest,
    HydratedSources,
    HydrateSourcesRequest,
    SourcesField,
    Target,
    Targets,
    UnexpandedTargets,
)


class PeekSubsystem(Outputting, GoalSubsystem):
    """Display detailed target information in JSON form."""

    name = "peek"
    help = "Display BUILD target info"

    @classmethod
    def register_options(cls, register):
        super().register_options(register)
        register(
            "--exclude-defaults",
            type=bool,
            default=False,
            help="Whether to leave off values that match the target-defined default values.",
        )

    @property
    def exclude_defaults(self) -> bool:
        return cast(bool, self.options.exclude_defaults)


class Peek(Goal):
    subsystem_cls = PeekSubsystem


@dataclass(frozen=True)
class TargetData:
    target: Target
    # These fields may not be registered on the target, so we have nothing to expand.
    expanded_sources: tuple[str, ...] | None
    expanded_dependencies: tuple[str, ...] | None


class TargetDatas(Collection[TargetData]):
    pass


def render_json(tds: Iterable[TargetData], exclude_defaults: bool = False) -> str:
    nothing = object()

    def normalize_value(val: Any) -> Any:
        if isinstance(val, collections.abc.Mapping):
            return {str(k): normalize_value(v) for k, v in val.items()}
        return val

    def to_json(td: TargetData) -> dict:
        fields = {
            (
                f"{k.alias}_raw" if issubclass(k, (SourcesField, Dependencies)) else k.alias
            ): normalize_value(v.value)
            for k, v in td.target.field_values.items()
            if not (exclude_defaults and getattr(k, "default", nothing) == v.value)
        }

        if td.expanded_dependencies is not None:
            fields["dependencies"] = td.expanded_dependencies
        if td.expanded_sources is not None:
            fields["sources"] = td.expanded_sources

        return {
            "address": td.target.address.spec,
            "target_type": td.target.alias,
            **dict(sorted(fields.items())),
        }

    return f"{json.dumps([to_json(td) for td in tds], indent=2, cls=_PeekJsonEncoder)}\n"


class _PeekJsonEncoder(json.JSONEncoder):
    """Allow us to serialize some commmonly found types in BUILD files."""

    def default(self, o):
        """Return a serializable object for o."""
        if is_dataclass(o):
            return asdict(o)
        if isinstance(o, collections.abc.Mapping):
            return dict(o)
        if isinstance(o, collections.abc.Sequence):
            return list(o)
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

    # We "hydrate" these field with the engine, but not every target has them registered.
    targets_with_dependencies = []
    targets_with_sources = []
    for tgt in sorted_targets:
        if tgt.has_field(Dependencies):
            targets_with_dependencies.append(tgt)
        if tgt.has_field(SourcesField):
            targets_with_sources.append(tgt)

    # NB: When determining dependencies, we replace target generators with their generated targets.
    dependencies_per_target = await MultiGet(
        Get(
            Targets,
            DependenciesRequest(tgt.get(Dependencies), include_special_cased_deps=True),
        )
        for tgt in targets_with_dependencies
    )
    hydrated_sources_per_target = await MultiGet(
        Get(HydratedSources, HydrateSourcesRequest(tgt[SourcesField]))
        for tgt in targets_with_sources
    )

    expanded_dependencies_map = {
        tgt.address: tuple(dep.address.spec for dep in deps)
        for tgt, deps in zip(targets_with_dependencies, dependencies_per_target)
    }
    expanded_sources_map = {
        tgt.address: hs.snapshot.files
        for tgt, hs in zip(targets_with_sources, hydrated_sources_per_target)
    }

    return TargetDatas(
        TargetData(
            tgt,
            expanded_dependencies=expanded_dependencies_map.get(tgt.address),
            expanded_sources=expanded_sources_map.get(tgt.address),
        )
        for tgt in sorted_targets
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
