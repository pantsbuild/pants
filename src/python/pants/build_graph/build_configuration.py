# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import logging
import typing
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any, Dict, Type, Union

from pants.build_graph.build_file_aliases import BuildFileAliases
from pants.build_graph.lifecycle import ExtensionLifecycleHandler
from pants.engine.rules import Rule, RuleIndex
from pants.engine.target import Target
from pants.engine.unions import UnionRule
from pants.option.optionable import Optionable
from pants.util.ordered_set import FrozenOrderedSet, OrderedSet

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class BuildConfiguration:
    """Stores the types and helper functions exposed to BUILD files."""

    registered_aliases: BuildFileAliases
    optionables: FrozenOrderedSet[Optionable]
    rules: FrozenOrderedSet[Rule]
    union_rules: FrozenOrderedSet[UnionRule]
    target_types: FrozenOrderedSet[Type[Target]]
    lifecycle_handlers: FrozenOrderedSet[ExtensionLifecycleHandler]

    @dataclass
    class Builder:
        _exposed_object_by_alias: Dict[Any, Any] = field(default_factory=dict)
        _exposed_context_aware_object_factory_by_alias: Dict[Any, Any] = field(default_factory=dict)
        _optionables: OrderedSet = field(default_factory=OrderedSet)
        _rules: OrderedSet = field(default_factory=OrderedSet)
        _union_rules: OrderedSet = field(default_factory=OrderedSet)
        _target_types: OrderedSet[Type[Target]] = field(default_factory=OrderedSet)
        _lifecycle_handlers: OrderedSet[ExtensionLifecycleHandler] = field(
            default_factory=OrderedSet
        )

        def registered_aliases(self) -> BuildFileAliases:
            """Return the registered aliases exposed in BUILD files.

            These returned aliases aren't so useful for actually parsing BUILD files.
            They are useful for generating online documentation.

            :returns: A new BuildFileAliases instance containing this BuildConfiguration's registered alias
                      mappings.
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
                raise TypeError("The aliases must be a BuildFileAliases, given {}".format(aliases))

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
            rule_index = RuleIndex.create(rules)
            self._rules.update(rule_index.rules)
            self._rules.update(rule_index.queries)
            self._union_rules.update(rule_index.union_rules)
            self.register_optionables(
                rule.output_type for rule in self._rules if issubclass(rule.output_type, Optionable)
            )

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

        def register_lifecycle_handlers(
            self, handlers: Union[typing.Iterable[ExtensionLifecycleHandler], typing.Any]
        ):
            if not isinstance(handlers, Iterable):
                raise TypeError(
                    f"The entrypoint `lifecycle_handlers` must return an iterable. Given {repr(handlers)}"
                )
            bad_elements = [
                handler
                for handler in handlers
                if not isinstance(handler, ExtensionLifecycleHandler)
            ]
            if bad_elements:
                raise TypeError(
                    "Every element of the entrypoint `lifecycle_handlers` must be a subclass of "
                    f"{ExtensionLifecycleHandler.__name__}. Bad elements: {bad_elements}."
                )
            self._lifecycle_handlers.update(handlers)

        def create(self) -> "BuildConfiguration":
            registered_aliases = BuildFileAliases(
                objects=self._exposed_object_by_alias.copy(),
                context_aware_object_factories=self._exposed_context_aware_object_factory_by_alias.copy(),
            )
            return BuildConfiguration(
                registered_aliases=registered_aliases,
                optionables=FrozenOrderedSet(self._optionables),
                rules=FrozenOrderedSet(self._rules),
                union_rules=FrozenOrderedSet(self._union_rules),
                target_types=FrozenOrderedSet(self._target_types),
                lifecycle_handlers=FrozenOrderedSet(self._lifecycle_handlers),
            )
