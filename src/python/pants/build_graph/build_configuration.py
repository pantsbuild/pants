# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import logging
import typing
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Type, Union

from pants.build_graph.build_file_aliases import BuildFileAliases
from pants.engine.rules import Rule, RuleIndex
from pants.engine.target import Target
from pants.option.optionable import Optionable
from pants.util.frozendict import FrozenDict
from pants.util.ordered_set import FrozenOrderedSet, OrderedSet

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class BuildConfiguration:
    """Stores the types and helper functions exposed to BUILD files."""

    _registered_aliases: BuildFileAliases
    _optionables: FrozenOrderedSet[Optionable]
    _rules: FrozenOrderedSet[Union[Rule, Callable]]
    _union_rules: FrozenDict[Type, FrozenOrderedSet[Type]]
    _target_types: FrozenOrderedSet[Type[Target]]

    def registered_aliases(self) -> BuildFileAliases:
        """Return the registered aliases exposed in BUILD files.

        These returned aliases aren't so useful for actually parsing BUILD files. They are useful
        for generating things like http://pantsbuild.github.io/build_dictionary.html.
        """
        return self._registered_aliases

    def optionables(self) -> FrozenOrderedSet[Optionable]:
        """Returns the registered Optionable types."""
        return self._optionables

    def rules(self) -> FrozenOrderedSet[Union[Callable, Rule]]:
        """Returns the registered rules."""
        return self._rules

    def union_rules(self) -> FrozenDict[Type, FrozenOrderedSet[Type]]:
        """Returns a mapping of registered union base types to the types of the union members."""
        return self._union_rules

    def target_types(self) -> FrozenOrderedSet[Type[Target]]:
        return self._target_types

    @dataclass
    class Builder:
        _target_by_alias: Dict[Any, Any] = field(default_factory=dict)
        _target_macro_factory_by_alias: Dict[Any, Any] = field(default_factory=dict)
        _exposed_object_by_alias: Dict[Any, Any] = field(default_factory=dict)
        _exposed_context_aware_object_factory_by_alias: Dict[Any, Any] = field(default_factory=dict)
        _optionables: OrderedSet = field(default_factory=OrderedSet)
        _rules: OrderedSet = field(default_factory=OrderedSet)
        _union_rules: Dict[Type, OrderedSet[Type]] = field(default_factory=dict)
        _target_types: OrderedSet[Type[Target]] = field(default_factory=OrderedSet)

        def registered_aliases(self) -> BuildFileAliases:
            """Return the registered aliases exposed in BUILD files.

            These returned aliases aren't so useful for actually parsing BUILD files.
            They are useful for generating things like http://pantsbuild.github.io/build_dictionary.html.

            :returns: A new BuildFileAliases instance containing this BuildConfiguration's registered alias
                      mappings.
            """
            target_factories_by_alias = self._target_by_alias.copy()
            target_factories_by_alias.update(self._target_macro_factory_by_alias)
            return BuildFileAliases(
                targets=target_factories_by_alias,
                objects=self._exposed_object_by_alias.copy(),
                context_aware_object_factories=self._exposed_context_aware_object_factory_by_alias.copy(),
            )

        def register_aliases(self, aliases):
            """Registers the given aliases to be exposed in parsed BUILD files.

            :param aliases: The BuildFileAliases to register.
            :type aliases: :class:`pants.build_graph.build_file_aliases.BuildFileAliases`
            """
            if not isinstance(aliases, BuildFileAliases):
                raise TypeError("The aliases must be a BuildFileAliases, given {}".format(aliases))

            for alias, target_type in aliases.target_types.items():
                self._register_target_alias(alias, target_type)

            for alias, target_macro_factory in aliases.target_macro_factories.items():
                self._register_target_macro_factory_alias(alias, target_macro_factory)

            for alias, obj in aliases.objects.items():
                self._register_exposed_object(alias, obj)

            for (
                alias,
                context_aware_object_factory,
            ) in aliases.context_aware_object_factories.items():
                self._register_exposed_context_aware_object_factory(
                    alias, context_aware_object_factory
                )

        # TODO(John Sirois): Warn on alias override across all aliases since they share a global
        # namespace in BUILD files.
        # See: https://github.com/pantsbuild/pants/issues/2151
        def _register_target_alias(self, alias, target_type):
            if alias in self._target_by_alias:
                logger.debug(
                    "Target alias {} has already been registered. Overwriting!".format(alias)
                )

            self._target_by_alias[alias] = target_type
            self.register_optionables(target_type.subsystems())

        def _register_target_macro_factory_alias(self, alias, target_macro_factory):
            if alias in self._target_macro_factory_by_alias:
                logger.debug(
                    "TargetMacro alias {} has already been registered. Overwriting!".format(alias)
                )

            self._target_macro_factory_by_alias[alias] = target_macro_factory
            for target_type in target_macro_factory.target_types:
                self.register_optionables(target_type.subsystems())

        def _register_exposed_object(self, alias, obj):
            if alias in self._exposed_object_by_alias:
                logger.debug(
                    "Object alias {} has already been registered. Overwriting!".format(alias)
                )

            self._exposed_object_by_alias[alias] = obj
            # obj doesn't implement any common base class, so we have to test for this attr.
            if hasattr(obj, "subsystems"):
                self.register_optionables(obj.subsystems())

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

        def register_optionables(self, optionables):
            """Registers the given subsystem types.

            :param optionables: The Optionable types to register.
            :type optionables: :class:`collections.Iterable` containing
                               :class:`pants.option.optionable.Optionable` subclasses.
            """
            if not isinstance(optionables, Iterable):
                raise TypeError("The optionables must be an iterable, given {}".format(optionables))
            optionables = tuple(optionables)
            if not optionables:
                return

            invalid_optionables = [
                s for s in optionables if not isinstance(s, type) or not issubclass(s, Optionable)
            ]
            if invalid_optionables:
                raise TypeError(
                    "The following items from the given optionables are not Optionable "
                    "subclasses:\n\t{}".format("\n\t".join(str(i) for i in invalid_optionables))
                )

            self._optionables.update(optionables)

        def register_rules(self, rules):
            """Registers the given rules.

            param rules: The rules to register.
            :type rules: :class:`collections.Iterable` containing
                         :class:`pants.engine.rules.Rule` instances.
            """
            if not isinstance(rules, Iterable):
                raise TypeError("The rules must be an iterable, given {!r}".format(rules))

            # "Index" the rules to normalize them and expand their dependencies.
            normalized_rules = RuleIndex.create(rules).normalized_rules()
            indexed_rules = normalized_rules.rules
            union_rules = normalized_rules.union_rules

            # Store the rules and record their dependency Optionables.
            self._rules.update(indexed_rules)
            for union_base, new_members in union_rules.items():
                existing_members = self._union_rules.get(union_base, None)
                if existing_members is None:
                    self._union_rules[union_base] = new_members
                else:
                    existing_members.update(new_members)
            dependency_optionables = {
                do
                for rule in indexed_rules
                for do in rule.dependency_optionables
                if rule.dependency_optionables
            }
            self.register_optionables(dependency_optionables)

        # NB: We expect the parameter to be Iterable[Type[Target]], but we can't be confident in this
        # because we pass whatever people put in their `register.py`s to this function; i.e., this is
        # an impure function that reads from the outside world. So, we use the type hint `Any` and
        # perform runtime type checking.
        def register_target_types(
            self, target_types: Union[typing.Iterable[Type[Target]], Any]
        ) -> None:
            """Registers the given target types."""
            if not isinstance(target_types, Iterable):
                raise TypeError(
                    f"The entrypoint `target_types` must return an iterable. Given {repr(target_types)}"
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
            self._target_types.update(target_types)

        def create(self) -> "BuildConfiguration":
            target_factories_by_alias = self._target_by_alias.copy()
            target_factories_by_alias.update(self._target_macro_factory_by_alias)
            registered_aliases = BuildFileAliases(
                targets=target_factories_by_alias,
                objects=self._exposed_object_by_alias.copy(),
                context_aware_object_factories=self._exposed_context_aware_object_factory_by_alias.copy(),
            )
            return BuildConfiguration(
                _registered_aliases=registered_aliases,
                _optionables=FrozenOrderedSet(self._optionables),
                _rules=FrozenOrderedSet(self._rules),
                _union_rules=FrozenDict(
                    (union_base, FrozenOrderedSet(union_members))
                    for union_base, union_members in self._union_rules.items()
                ),
                _target_types=FrozenOrderedSet(self._target_types),
            )
