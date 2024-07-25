# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, DefaultDict

from pants.backend.project_info.filter_targets import FilterSubsystem
from pants.build_graph.build_file_aliases import BuildFileAliases
from pants.core.util_rules.environments import EnvironmentsSubsystem
from pants.engine.goal import GoalSubsystem
from pants.engine.rules import Rule, RuleIndex
from pants.engine.target import Target
from pants.engine.unions import UnionRule
from pants.option.alias import CliOptions
from pants.option.global_options import GlobalOptions
from pants.option.scope import normalize_scope
from pants.option.subsystem import Subsystem
from pants.util.frozendict import FrozenDict
from pants.util.ordered_set import FrozenOrderedSet
from pants.vcs.changed import Changed

logger = logging.getLogger(__name__)


# No goal or target_type can have a name from this set, so that `./pants help <name>`
# is unambiguous.
_RESERVED_NAMES = {
    "api-types",
    "backends",
    "global",
    "goals",
    "subsystems",
    "symbols",
    "targets",
    "tools",
}


# Subsystems used outside of any rule.
_GLOBAL_SUBSYSTEMS: set[type[Subsystem]] = {
    GlobalOptions,
    Changed,
    CliOptions,
    FilterSubsystem,
    EnvironmentsSubsystem,
}


@dataclass(frozen=True)
class BuildConfiguration:
    """Stores the types and helper functions exposed to BUILD files."""

    registered_aliases: BuildFileAliases
    subsystem_to_providers: FrozenDict[type[Subsystem], tuple[str, ...]]
    target_type_to_providers: FrozenDict[type[Target], tuple[str, ...]]
    rule_to_providers: FrozenDict[Rule, tuple[str, ...]]
    union_rule_to_providers: FrozenDict[UnionRule, tuple[str, ...]]
    allow_unknown_options: bool
    remote_auth_plugin_func: Callable | None

    @property
    def all_subsystems(self) -> tuple[type[Subsystem], ...]:
        """Return all subsystems in the system: global and those registered via rule usage."""
        # Sort by options_scope, for consistency.
        return tuple(
            sorted(
                _GLOBAL_SUBSYSTEMS | self.subsystem_to_providers.keys(),
                key=lambda x: x.options_scope,
            )
        )

    @property
    def target_types(self) -> tuple[type[Target], ...]:
        return tuple(sorted(self.target_type_to_providers.keys(), key=lambda x: x.alias))

    @property
    def rules(self) -> FrozenOrderedSet[Rule]:
        return FrozenOrderedSet(self.rule_to_providers.keys())

    @property
    def union_rules(self) -> FrozenOrderedSet[UnionRule]:
        return FrozenOrderedSet(self.union_rule_to_providers.keys())

    def __post_init__(self) -> None:
        class Category(Enum):
            goal = "goal"
            reserved_name = "reserved name"
            subsystem = "subsystem"
            target_type = "target type"

        name_to_categories: DefaultDict[str, set[Category]] = defaultdict(set)
        normalized_to_orig_name: dict[str, str] = {}

        for opt in self.all_subsystems:
            scope = opt.options_scope
            normalized_scope = normalize_scope(scope)
            name_to_categories[normalized_scope].add(
                Category.goal if issubclass(opt, GoalSubsystem) else Category.subsystem
            )
            normalized_to_orig_name[normalized_scope] = scope
        for tgt_type in self.target_types:
            name_to_categories[normalize_scope(tgt_type.alias)].add(Category.target_type)
        for reserved_name in _RESERVED_NAMES:
            name_to_categories[normalize_scope(reserved_name)].add(Category.reserved_name)

        found_collision = False
        for name, cats in name_to_categories.items():
            if len(cats) > 1:
                scats = sorted(cat.value for cat in cats)
                cats_str = ", ".join(f"a {cat}" for cat in scats[:-1]) + f" and a {scats[-1]}."
                colliding_names = "`/`".join(
                    sorted({name, normalized_to_orig_name.get(name, name)})
                )
                logger.error(f"Naming collision: `{colliding_names}` is registered as {cats_str}")
                found_collision = True

        if found_collision:
            raise TypeError("Found naming collisions. See log for details.")

    @dataclass
    class Builder:
        _exposed_object_by_alias: dict[Any, Any] = field(default_factory=dict)
        _exposed_context_aware_object_factory_by_alias: dict[Any, Any] = field(default_factory=dict)
        _subsystem_to_providers: dict[type[Subsystem], list[str]] = field(
            default_factory=lambda: defaultdict(list)
        )
        _target_type_to_providers: dict[type[Target], list[str]] = field(
            default_factory=lambda: defaultdict(list)
        )
        _rule_to_providers: dict[Rule, list[str]] = field(default_factory=lambda: defaultdict(list))
        _union_rule_to_providers: dict[UnionRule, list[str]] = field(
            default_factory=lambda: defaultdict(list)
        )
        _allow_unknown_options: bool = False
        _remote_auth_plugin: Callable | None = None

        def registered_aliases(self) -> BuildFileAliases:
            """Return the registered aliases exposed in BUILD files.

            These returned aliases aren't so useful for actually parsing BUILD files.
            They are useful for generating online documentation.

            :returns: A new BuildFileAliases instance containing this BuildConfiguration's
                      registered alias mappings.
            """
            return BuildFileAliases(
                objects=self._exposed_object_by_alias.copy(),
                context_aware_object_factories=self._exposed_context_aware_object_factory_by_alias.copy(),
            )

        def register_aliases(self, aliases):
            """Registers the given aliases to be exposed in parsed BUILD files.

            :param aliases: The BuildFileAliases to register.
            :type aliases: :class:`pants.build_graph.build_file_aliases.BuildFileAliases`
            """
            if not isinstance(aliases, BuildFileAliases):
                raise TypeError(f"The aliases must be a BuildFileAliases, given {aliases}")

            for alias, obj in aliases.objects.items():
                self._register_exposed_object(alias, obj)

            for (
                alias,
                context_aware_object_factory,
            ) in aliases.context_aware_object_factories.items():
                self._register_exposed_context_aware_object_factory(
                    alias, context_aware_object_factory
                )

        def _register_exposed_object(self, alias, obj):
            if alias in self._exposed_object_by_alias:
                logger.debug(f"Object alias {alias} has already been registered. Overwriting!")

            self._exposed_object_by_alias[alias] = obj

        def _register_exposed_context_aware_object_factory(
            self, alias, context_aware_object_factory
        ):
            if alias in self._exposed_context_aware_object_factory_by_alias:
                logger.debug(
                    "This context aware object factory alias {} has already been registered. "
                    "Overwriting!".format(alias)
                )

            self._exposed_context_aware_object_factory_by_alias[
                alias
            ] = context_aware_object_factory

        def register_subsystems(
            self, plugin_or_backend: str, subsystems: Iterable[type[Subsystem]]
        ):
            """Registers the given subsystem types."""
            if not isinstance(subsystems, Iterable):
                raise TypeError(f"The subsystems must be an iterable, given {subsystems}")
            subsystems = tuple(subsystems)
            if not subsystems:
                return

            invalid_subsystems = [
                s for s in subsystems if not isinstance(s, type) or not issubclass(s, Subsystem)
            ]
            if invalid_subsystems:
                raise TypeError(
                    "The following items from the given subsystems are not Subsystems "
                    "subclasses:\n\t{}".format("\n\t".join(str(i) for i in invalid_subsystems))
                )

            for subsystem in subsystems:
                self._subsystem_to_providers[subsystem].append(plugin_or_backend)

        def register_rules(self, plugin_or_backend: str, rules: Iterable[Rule | UnionRule]):
            """Registers the given rules."""
            if not isinstance(rules, Iterable):
                raise TypeError(f"The rules must be an iterable, given {rules!r}")

            # "Index" the rules to normalize them and expand their dependencies.
            rule_index = RuleIndex.create(rules)
            rules_and_queries: tuple[Rule, ...] = (*rule_index.rules, *rule_index.queries)
            for rule in rules_and_queries:
                self._rule_to_providers[rule].append(plugin_or_backend)
            for union_rule in rule_index.union_rules:
                self._union_rule_to_providers[union_rule].append(plugin_or_backend)
            self.register_subsystems(
                plugin_or_backend,
                (
                    rule.output_type
                    for rule in rules_and_queries
                    if issubclass(rule.output_type, Subsystem)
                ),
            )

        # NB: We expect the parameter to be Iterable[Type[Target]], but we can't be confident in
        # this because we pass whatever people put in their `register.py`s to this function;
        # I.e., this is an impure function that reads from the outside world. So, we use the type
        # hint `Any` and perform runtime type checking.
        def register_target_types(
            self, plugin_or_backend: str, target_types: Iterable[type[Target]] | Any
        ) -> None:
            """Registers the given target types."""
            if not isinstance(target_types, Iterable):
                raise TypeError(
                    f"The entrypoint `target_types` must return an iterable. "
                    f"Given {repr(target_types)}"
                )
            bad_elements = [
                tgt_type
                for tgt_type in target_types
                if not isinstance(tgt_type, type) or not issubclass(tgt_type, Target)
            ]
            if bad_elements:
                raise TypeError(
                    "Every element of the entrypoint `target_types` must be a subclass of "
                    f"{Target.__name__}. Bad elements: {bad_elements}."
                )
            for target_type in target_types:
                self._target_type_to_providers[target_type].append(plugin_or_backend)
                # Access the Target.PluginField here to ensure the PluginField class is
                # created before the UnionMembership is instantiated, as the class hierarchy is
                # walked during union membership setup.
                _ = target_type.PluginField

        def register_remote_auth_plugin(self, remote_auth_plugin: Callable) -> None:
            self._remote_auth_plugin = remote_auth_plugin

        def register_auxiliary_goals(self, plugin_or_backend: str, auxiliary_goals: Iterable[type]):
            """Registers the given auxiliary goals."""
            if not isinstance(auxiliary_goals, Iterable):
                raise TypeError(
                    f"The entrypoint `auxiliary_goals` must return an iterable. "
                    f"Given {repr(auxiliary_goals)}"
                )
            # Import `AuxiliaryGoal` here to avoid import cycle.
            from pants.goal.auxiliary_goal import AuxiliaryGoal

            bad_elements = [goal for goal in auxiliary_goals if not issubclass(goal, AuxiliaryGoal)]
            if bad_elements:
                raise TypeError(
                    "Every element of the entrypoint `auxiliary_goals` must be a subclass of "
                    f"{AuxiliaryGoal.__name__}. Bad elements: {bad_elements}."
                )
            self.register_subsystems(plugin_or_backend, auxiliary_goals)

        def allow_unknown_options(self, allow: bool = True) -> None:
            """Allows overriding whether Options parsing will fail for unrecognized Options.

            Used to defer options failures while bootstrapping BuildConfiguration until after the
            complete set of plugins is known.
            """
            self._allow_unknown_options = True

        def create(self) -> BuildConfiguration:
            registered_aliases = BuildFileAliases(
                objects=self._exposed_object_by_alias.copy(),
                context_aware_object_factories=self._exposed_context_aware_object_factory_by_alias.copy(),
            )
            return BuildConfiguration(
                registered_aliases=registered_aliases,
                subsystem_to_providers=FrozenDict(
                    (k, tuple(v)) for k, v in self._subsystem_to_providers.items()
                ),
                target_type_to_providers=FrozenDict(
                    (k, tuple(v)) for k, v in self._target_type_to_providers.items()
                ),
                rule_to_providers=FrozenDict(
                    (k, tuple(v)) for k, v in self._rule_to_providers.items()
                ),
                union_rule_to_providers=FrozenDict(
                    (k, tuple(v)) for k, v in self._union_rule_to_providers.items()
                ),
                allow_unknown_options=self._allow_unknown_options,
                remote_auth_plugin_func=self._remote_auth_plugin,
            )
