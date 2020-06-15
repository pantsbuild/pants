# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import inspect
from abc import abstractmethod
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Callable, Dict, FrozenSet, Optional, Tuple, Type, Union, cast

from pants.base.build_file_target_factory import BuildFileTargetFactory
from pants.base.parse_context import ParseContext
from pants.build_graph.target import Target
from pants.util.frozendict import FrozenDict
from pants.util.memo import memoized_property
from pants.util.meta import frozen_after_init

ContextAwareObjectFactory = Callable[[ParseContext], Callable[..., None]]


class TargetMacro:
    """A specialized context aware object factory responsible for instantiating a set of target
    types.

    The macro acts to expand arguments to its alias in a BUILD file into one or more target
    addressable instances.  This is primarily useful for hiding true target type constructors from
    BUILD file authors and providing an extra layer of control over core target parameters like
    `name` and `dependencies`.
    """

    class Factory(BuildFileTargetFactory):
        """Creates new target macros specialized for a particular BUILD file parse context."""

        @classmethod
        def wrap(cls, context_aware_object_factory, *target_types):
            """Wraps an existing context aware object factory into a target macro factory.

            :param context_aware_object_factory: The existing context aware object factory.
            :param *target_types: One or more target types the context aware object factory creates.
            :returns: A new target macro factory.
            :rtype: :class:`TargetMacro.Factory`
            """
            if not target_types:
                raise ValueError(
                    "The given `context_aware_object_factory` {} must expand 1 produced "
                    "type; none were registered".format(context_aware_object_factory)
                )

            class Factory(cls):
                @property
                def target_types(self):
                    return target_types

                def macro(self, parse_context):
                    class Macro(TargetMacro):
                        def expand(self, *args, **kwargs):
                            context_aware_object_factory(parse_context, *args, **kwargs)

                    return Macro()

            return Factory()

        @abstractmethod
        def macro(self, parse_context):
            """Returns a new target macro that can create targets in the given parse context.

            :param parse_context: The parse context the target macro will expand targets in.
            :type parse_context: :class:`pants.base.parse_context.ParseContext`
            :rtype: :class:`TargetMacro`
            """

        def target_macro(self, parse_context):
            """Returns a new target macro that can create targets in the given parse context.

            The target macro will also act as a build file target factory and report the target types it
            creates.

            :param parse_context: The parse context the target macro will expand targets in.
            :type parse_context: :class:`pants.base.parse_context.ParseContext`
            :rtype: :class:`BuildFileTargetFactory` & :class:`TargetMacro`
            """
            macro = self.macro(parse_context)

            return _BuildFileTargetFactoryMacro(macro.expand, self.target_types)

    def __call__(self, *args, **kwargs):
        self.expand(*args, **kwargs)

    @abstractmethod
    def expand(self, *args, **kwargs):
        """Expands the given BUILD file arguments in to one or more target addressable instances."""


@frozen_after_init
@dataclass(unsafe_hash=True)
class BuildFileAliases:
    """A structure containing sets of symbols to be exposed in BUILD files.

    There are three types of symbols that can be directly exposed:

    :API: public

    - targets: These are Target subclasses or TargetMacro.Factory instances.
    - objects: These are any python object, from constants to types.
    - context_aware_object_factories: These are object factories that are passed a ParseContext and
      produce one or more objects that use data from the context to enable some feature or utility;
      you might call them a BUILD file "macro" since they expand parameters to some final, "real"
      BUILD file object.  Common uses include creating objects that must be aware of the current
      BUILD file path or functions that need to be able to create targets or objects from within the
      BUILD file parse.
    """

    _target_types: FrozenDict[str, Type[Target]]
    _target_macro_factories: FrozenDict[str, TargetMacro.Factory]
    _objects: FrozenDict[str, Any]
    _context_aware_object_factories: FrozenDict[str, ContextAwareObjectFactory]

    @staticmethod
    def _is_target_type(obj: Any) -> bool:
        return inspect.isclass(obj) and issubclass(obj, Target)

    @staticmethod
    def _is_target_macro_factory(obj: Any) -> bool:
        return isinstance(obj, TargetMacro.Factory)

    @classmethod
    def _validate_alias(cls, category: str, alias: str, obj: Any) -> None:
        if not isinstance(alias, str):
            raise TypeError(
                "Aliases must be strings, given {category} entry {alias!r} of type {typ} as "
                "the alias of {obj}".format(
                    category=category, alias=alias, typ=type(alias).__name__, obj=obj
                )
            )

    @classmethod
    def _validate_not_targets(cls, category: str, alias: str, obj: Any) -> None:
        if cls._is_target_type(obj):
            raise TypeError(
                "The {category} entry {alias!r} is a Target subclasss - these should be "
                "registered via the `targets` parameter".format(category=category, alias=alias)
            )
        if cls._is_target_macro_factory(obj):
            raise TypeError(
                "The {category} entry {alias!r} is a TargetMacro.Factory instance - these "
                "should be registered via the `targets` parameter".format(
                    category=category, alias=alias
                )
            )

    @classmethod
    def _validate_targets(
        cls, targets: Optional[Dict[str, Union[Type[Target], TargetMacro.Factory]]],
    ) -> Tuple[FrozenDict[str, Type[Target]], FrozenDict[str, TargetMacro.Factory]]:
        if not targets:
            return FrozenDict(), FrozenDict()

        target_types = {}
        target_macro_factories = {}
        for alias, obj in targets.items():
            cls._validate_alias("targets", alias, obj)
            if cls._is_target_type(obj):
                target_types[alias] = cast(Type[Target], obj)
            elif cls._is_target_macro_factory(obj):
                target_macro_factories[alias] = cast(TargetMacro.Factory, obj)
            else:
                raise TypeError(
                    "Only Target types and TargetMacro.Factory instances can be registered "
                    "via the `targets` parameter, given item {alias!r} with value {value} of "
                    "type {typ}".format(alias=alias, value=obj, typ=type(obj).__name__)
                )

        return FrozenDict(target_types), FrozenDict(target_macro_factories)

    @classmethod
    def _validate_objects(cls, objects: Optional[Dict[str, Any]]) -> FrozenDict[str, Any]:
        if not objects:
            return FrozenDict()

        for alias, obj in objects.items():
            cls._validate_alias("objects", alias, obj)
            cls._validate_not_targets("objects", alias, obj)
        return FrozenDict(objects)

    @classmethod
    def _validate_context_aware_object_factories(
        cls, context_aware_object_factories: Optional[Dict[str, ContextAwareObjectFactory]]
    ) -> FrozenDict[str, ContextAwareObjectFactory]:
        if not context_aware_object_factories:
            return FrozenDict()

        for alias, obj in context_aware_object_factories.items():
            cls._validate_alias("context_aware_object_factories", alias, obj)
            cls._validate_not_targets("context_aware_object_factories", alias, obj)
            if not callable(obj):
                raise TypeError(
                    "The given context aware object factory {alias!r} must be a callable.".format(
                        alias=alias
                    )
                )

        return FrozenDict(context_aware_object_factories)

    def __init__(
        self,
        targets: Optional[Dict[str, Union[Type[Target], TargetMacro.Factory]]] = None,
        objects: Optional[Dict[str, Any]] = None,
        context_aware_object_factories: Optional[Dict[str, ContextAwareObjectFactory]] = None,
    ) -> None:
        """
        :API: public
        """
        self._target_types, self._target_macro_factories = self._validate_targets(targets)
        self._objects = self._validate_objects(objects)
        self._context_aware_object_factories = self._validate_context_aware_object_factories(
            context_aware_object_factories
        )

    @property
    def target_types(self) -> FrozenDict[str, Type[Target]]:
        """
        :API: public
        """
        return self._target_types

    @property
    def target_macro_factories(self) -> FrozenDict[str, TargetMacro.Factory]:
        """
        :API: public
        """
        return self._target_macro_factories

    @property
    def objects(self) -> FrozenDict[str, Any]:
        """
        :API: public
        """
        return self._objects

    @property
    def context_aware_object_factories(self) -> FrozenDict[str, ContextAwareObjectFactory]:
        """
        :API: public
        """
        return self._context_aware_object_factories

    @memoized_property
    def target_types_by_alias(self) -> FrozenDict[str, FrozenSet[Type[Target]]]:
        """Returns a mapping from target alias to the target types produced for that alias.

        Normally there is 1 target type per alias, but macros can expand a single alias to several
        target types.

        :API: public

        :rtype: dict
        """
        target_types_by_alias = defaultdict(list)
        for alias, target_type in self.target_types.items():
            target_types_by_alias[alias].append(target_type)
        for alias, target_macro_factory in self.target_macro_factories.items():
            target_types_by_alias[alias].extend(target_macro_factory.target_types)
        return FrozenDict(
            (alias, frozenset(target_types))
            for alias, target_types in target_types_by_alias.items()
        )

    def merge(self, other: "BuildFileAliases") -> "BuildFileAliases":
        """Merges a set of build file aliases and returns a new set of aliases containing both.

        Any duplicate aliases from `other` will trump.

        :API: public
        """
        if not isinstance(other, BuildFileAliases):
            raise TypeError("Can only merge other BuildFileAliases, given {0}".format(other))

        def merge(*items):
            merged: Dict = {}
            for item in items:
                merged.update(item)
            return merged

        targets = merge(
            self.target_types,
            self.target_macro_factories,
            other.target_types,
            other.target_macro_factories,
        )
        objects = merge(self.objects, other.objects)
        context_aware_object_factories = merge(
            self.context_aware_object_factories, other.context_aware_object_factories
        )
        return BuildFileAliases(
            targets=targets,
            objects=objects,
            context_aware_object_factories=context_aware_object_factories,
        )


class _BuildFileTargetFactoryMacro(BuildFileTargetFactory, TargetMacro):
    def __init__(self, expand, target_types):
        self._target_types = target_types
        self.expand = expand

    def target_types(self):
        return self._target_types
