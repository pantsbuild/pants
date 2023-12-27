# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import collections
import collections.abc
import json
import logging
from dataclasses import dataclass, fields, is_dataclass
from typing import Any, Iterable, Mapping

from typing_extensions import Protocol, runtime_checkable

from pants.core.goals.deploy import DeployFieldSet
from pants.core.goals.package import PackageFieldSet
from pants.core.goals.publish import PublishFieldSet
from pants.core.goals.run import RunFieldSet
from pants.core.goals.test import TestFieldSet
from pants.engine.addresses import Address, Addresses
from pants.engine.collection import Collection
from pants.engine.console import Console
from pants.engine.fs import Snapshot
from pants.engine.goal import Goal, GoalSubsystem, Outputting
from pants.engine.internals.build_files import _get_target_family_and_adaptor_for_dep_rules
from pants.engine.internals.dep_rules import DependencyRuleApplication, DependencyRuleSet
from pants.engine.rules import Get, MultiGet, Rule, collect_rules, goal_rule, rule
from pants.engine.target import (
    AlwaysTraverseDeps,
    Dependencies,
    DependenciesRequest,
    DependenciesRuleApplication,
    DependenciesRuleApplicationRequest,
    Field,
    FieldSet,
    HydratedSources,
    HydrateSourcesRequest,
    NoApplicableTargetsBehavior,
    SourcesField,
    Target,
    TargetRootsToFieldSets,
    TargetRootsToFieldSetsRequest,
    Targets,
    UnexpandedTargets,
)
from pants.option.option_types import BoolOption
from pants.util.strutil import softwrap

logger = logging.getLogger(__name__)


@runtime_checkable
class Dictable(Protocol):
    """Make possible to avoid adding concrete types to serialize objects."""

    def asdict(self) -> Mapping[str, Any]:
        ...


class PeekSubsystem(Outputting, GoalSubsystem):
    """Display detailed target information in JSON form."""

    name = "peek"
    help = "Display BUILD target info"

    exclude_defaults = BoolOption(
        default=False,
        help="Whether to leave off values that match the target-defined default values.",
    )

    include_dep_rules = BoolOption(
        default=False,
        help=softwrap(
            """
            Whether to include `_dependencies_rules`, `_dependents_rules` and `_applicable_dep_rules`
            that apply to the target and its dependencies.
            """
        ),
    )

    include_goals = BoolOption(
        default=False,
        help=softwrap(
            """
            Whether to include the goals that apply to the target and its dependencies. These are the
            embedded in JSON as `goals`.
            """
        ),
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
    expanded_sources: Snapshot | None
    expanded_dependencies: tuple[str, ...]

    dependencies_rules: tuple[str, ...] | None = None
    dependents_rules: tuple[str, ...] | None = None
    applicable_dep_rules: tuple[DependencyRuleApplication, ...] | None = None

    goals: tuple[str, ...] | None = None

    def to_dict(self, exclude_defaults: bool = False, include_dep_rules: bool = False) -> dict:
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
            fields["sources"] = self.expanded_sources.files
            fields["sources_fingerprint"] = self.expanded_sources.digest.fingerprint

        if include_dep_rules:
            fields["_dependencies_rules"] = self.dependencies_rules
            fields["_dependents_rules"] = self.dependents_rules
            fields["_applicable_dep_rules"] = self.applicable_dep_rules

        if self.goals is not None:
            fields["goals"] = self.goals

        return {
            "address": self.target.address.spec,
            "target_type": self.target.alias,
            **dict(sorted(fields.items())),
        }

    # def as_dict(self) -> Mapping[str, Any]:
    #     return asdict(self)


class TargetDatas(Collection[TargetData]):
    pass


def render_json(
    tds: Iterable[TargetData], exclude_defaults: bool = False, include_dep_rules: bool = False
) -> str:
    return f"{json.dumps([td.to_dict(exclude_defaults, include_dep_rules) for td in tds], indent=2, cls=_PeekJsonEncoder)}\n"


class _PeekJsonEncoder(json.JSONEncoder):
    """Allow us to serialize some commmonly found types in BUILD files."""

    def default(self, o):
        """Return a serializable object for o."""
        if isinstance(o, str):  # early exit prevents strings from being treated as sequences
            return o
        if o is None:
            return o
        if is_dataclass(o):
            # NB: `dataclasses.asdict` creates a deep copy by default, which is unnecessary for
            # this case.
            return {field.name: getattr(o, field.name) for field in fields(o)}
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
        if isinstance(o, Dictable):
            return o.asdict()
        try:
            return super().default(o)
        except TypeError:
            return str(o)


def describe_ruleset(ruleset: DependencyRuleSet | None) -> tuple[str, ...] | None:
    if ruleset is None:
        return None
    return ruleset.peek()


async def _create_target_alias_to_goals_map() -> dict[str, tuple[str, ...]]:
    """Returns a mapping from a target alias to the goals that can operate on that target.

    For instance, `pex_binary` would map to `("run", "package")`.

    :return: A mapping from a target alias to the goals that can operate on that target.
    """
    # TODO: This is manually curated for now - do we want to show all possible goals?
    peekable_field_sets: list[type[FieldSet]] = [
        DeployFieldSet,
        PackageFieldSet,
        PublishFieldSet,
        RunFieldSet,
        TestFieldSet,
    ]
    # TODO: How do we get the goal subsystem from field set? This shouldn't need to be manually maintained
    field_set_to_goal_map: dict[type[FieldSet], str] = {
        DeployFieldSet: "experimental-deploy",
        PackageFieldSet: "package",
        PublishFieldSet: "publish",
        RunFieldSet: "run",
        TestFieldSet: "test",
    }
    assert len(peekable_field_sets) == len(
        field_set_to_goal_map
    ), "Must have a goal string for each field set"
    peekable_goals = [field_set_to_goal_map[fs] for fs in peekable_field_sets]

    target_roots_to_field_sets_get = [
        Get(
            TargetRootsToFieldSets,
            TargetRootsToFieldSetsRequest(
                field_set_superclass=fs,
                goal_description="",
                no_applicable_targets_behavior=NoApplicableTargetsBehavior.ignore,
            ),
        )
        for fs in peekable_field_sets
    ]

    target_roots_to_field_sets = await MultiGet(target_roots_to_field_sets_get)

    # Create a collection of target aliases per target roots: e.g. [frozenset(), frozenset({'pyoxidizer_binary', 'pex_binary'}), ...]
    aliases_per_target_root: Iterable[frozenset[str]] = [
        frozenset(tgt.alias for tgt in tgt_root.targets) for tgt_root in target_roots_to_field_sets
    ]

    # Create a mapping from the goal name to a collection of target aliases: e.g. {'run': frozenset({'pyoxidizer_binary', 'pex_binary'}), 'test': frozenset(), ...}
    goal_to_aliases_map = dict(zip(peekable_goals, aliases_per_target_root))

    # Inverse the goal_to_aliases_map to create a mapping from a target alias to a collection of goal names: e.g. {'pyoxidizer_binary': frozenset({'package', 'run'}), 'pex_binary': frozenset({'package', 'run'}), ...}
    alias_to_goals_map: Mapping[str, set[str]] = {}
    for goal, aliases in goal_to_aliases_map.items():
        for alias in aliases:
            alias_to_goals_map.setdefault(alias, set()).add(goal)

    # Convert the goal sets to tuples for JSON serialization
    return {alias: tuple(sorted(goals)) for alias, goals in alias_to_goals_map.items()}


@rule
async def get_target_data(
    targets: UnexpandedTargets,
    subsys: PeekSubsystem,
) -> TargetDatas:
    """Given a set of unexpanded targets, return a mapping of target addresses to their data.

    The data includes the target's fields, expanded sources, expanded dependencies, and any
    dependency rules that apply to the target.

    NB: We must preserve target generators, not replace with their generated targets.

    :param targets: The unexpanded targets to get data for.
    :param subsys: The `PeekSubsystem` instance.
    :return: A mapping of target addresses to their data.
    """
    sorted_targets = sorted(targets, key=lambda tgt: tgt.address)

    # We "hydrate" sources fields with the engine, but not every target has them registered.
    targets_with_sources = [tgt for tgt in sorted_targets if tgt.has_field(SourcesField)]

    # When determining dependencies, we replace target generators with their generated targets.
    dependencies_per_target = await MultiGet(
        Get(
            Targets,
            DependenciesRequest(
                tgt.get(Dependencies), should_traverse_deps_predicate=AlwaysTraverseDeps()
            ),
        )
        for tgt in sorted_targets
    )
    hydrated_sources_per_target = await MultiGet(
        Get(HydratedSources, HydrateSourcesRequest(tgt[SourcesField]))
        for tgt in targets_with_sources
    )

    # TODO: This feels like something that could be merged with the above code somewhere
    expanded_sources_map = {
        tgt.address: hs.snapshot
        for tgt, hs in zip(targets_with_sources, hydrated_sources_per_target)
    }

    expanded_dependencies = [
        tuple(dep.address.spec for dep in deps)
        for _, deps in zip(sorted_targets, dependencies_per_target)
    ]

    dependencies_rules_map: dict[Address, tuple[str, ...] | None] = {}
    dependents_rules_map: dict[Address, tuple[str, ...] | None] = {}
    # applicable_dep_rules_map: dict[Address, tuple[DependenciesRuleApplication, ...]] = {}
    applicable_dep_rules_map = {}

    if subsys.include_dep_rules:
        # TODO: Why are we pulling a private definition from `build_files`?
        family_adaptors = await _get_target_family_and_adaptor_for_dep_rules(
            *(tgt.address for tgt in sorted_targets),
            description_of_origin="`peek` goal",
        )

        dependencies_rules_map = {
            tgt.address: describe_ruleset(
                family.dependencies_rules.get_ruleset(tgt.address, adaptor)
            )
            for tgt, (family, adaptor) in zip(sorted_targets, family_adaptors)
            if family.dependencies_rules is not None
        }

        dependents_rules_map = {
            tgt.address: describe_ruleset(family.dependents_rules.get_ruleset(tgt.address, adaptor))
            for tgt, (family, adaptor) in zip(sorted_targets, family_adaptors)
            if family.dependents_rules is not None
        }

        all_applicable_dep_rules = await MultiGet(
            Get(
                DependenciesRuleApplication,
                DependenciesRuleApplicationRequest(
                    tgt.address,
                    Addresses(dep.address for dep in deps),
                    description_of_origin="`peek` goal",
                ),
            )
            for tgt, deps in zip(sorted_targets, dependencies_per_target)
        )
        applicable_dep_rules_map = {
            application.address: tuple(application.dependencies_rule.values())
            for application in all_applicable_dep_rules
        }

    # target_alias_to_goals_map = await _create_target_alias_to_goals_map() if subsys.include_goals else {}

    return TargetDatas(
        TargetData(
            tgt,
            expanded_dependencies=expanded_deps,
            expanded_sources=expanded_sources_map.get(tgt.address),
            dependencies_rules=dependencies_rules_map.get(tgt.address),
            dependents_rules=dependents_rules_map.get(tgt.address),
            applicable_dep_rules=applicable_dep_rules_map.get(tgt.address),
            goals=None,
        )
        for tgt, expanded_deps in zip(sorted_targets, expanded_dependencies)
    )


@goal_rule
async def peek(
    console: Console,
    subsys: PeekSubsystem,
    targets: UnexpandedTargets,
) -> Peek:
    """Display detailed target information in JSON form.

    :param console: The console to write the JSON to.
    :param subsys: The `PeekSubsystem` instance.
    :param targets: The targets to get data for.
    :return: The `Peek` goal.
    """

    tds = await Get(TargetDatas, UnexpandedTargets, targets)
    # TODO: This method needs to be called in a @goal_rule, otherwise it fails out with Rule errors (when called in an @rule)
    target_alias_to_goals_map = (
        await _create_target_alias_to_goals_map() if subsys.include_goals else {}
    )

    if target_alias_to_goals_map:
        # Attach the goals to the target data, in the hopes that we can pull `_create_target_alias_to_goals_map` back into `get_target_data`
        # TargetData is frozen so we need to create a new collection
        tds = [
            TargetData(
                td.target,
                td.expanded_sources,
                td.expanded_dependencies,
                td.dependencies_rules,
                td.dependents_rules,
                td.applicable_dep_rules,
                target_alias_to_goals_map.get(td.target.alias),
            )
            for td in tds
        ]
    output = render_json(tds, subsys.exclude_defaults, subsys.include_dep_rules)

    with subsys.output(console) as write_stdout:
        write_stdout(output)
    return Peek(exit_code=0)


def rules() -> Iterable[Rule]:
    return collect_rules()
