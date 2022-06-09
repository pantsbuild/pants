# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from pants.base.parse_context import ParseContext
from pants.util.frozendict import FrozenDict
from pants.util.meta import frozen_after_init

ContextAwareObjectFactory = Callable[[ParseContext], Callable[..., None]]


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

    _objects: FrozenDict[str, Any]
    _context_aware_object_factories: FrozenDict[str, ContextAwareObjectFactory]

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
    def _validate_objects(cls, objects: dict[str, Any] | None) -> FrozenDict[str, Any]:
        if not objects:
            return FrozenDict()

        for alias, obj in objects.items():
            cls._validate_alias("objects", alias, obj)
        return FrozenDict(objects)

    @classmethod
    def _validate_context_aware_object_factories(
        cls, context_aware_object_factories: dict[str, ContextAwareObjectFactory] | None
    ) -> FrozenDict[str, ContextAwareObjectFactory]:
        if not context_aware_object_factories:
            return FrozenDict()

        for alias, obj in context_aware_object_factories.items():
            cls._validate_alias("context_aware_object_factories", alias, obj)
            if not callable(obj):
                raise TypeError(
                    "The given context aware object factory {alias!r} must be a callable.".format(
                        alias=alias
                    )
                )

        return FrozenDict(context_aware_object_factories)

    def __init__(
        self,
        objects: dict[str, Any] | None = None,
        context_aware_object_factories: dict[str, ContextAwareObjectFactory] | None = None,
    ) -> None:
        """
        :API: public
        """
        self._objects = self._validate_objects(objects)
        self._context_aware_object_factories = self._validate_context_aware_object_factories(
            context_aware_object_factories
        )

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

    def merge(self, other: BuildFileAliases) -> BuildFileAliases:
        """Merges a set of build file aliases and returns a new set of aliases containing both.

        Any duplicate aliases from `other` will trump.

        :API: public
        """
        if not isinstance(other, BuildFileAliases):
            raise TypeError(f"Can only merge other BuildFileAliases, given {other}")

        def merge(*items):
            merged: dict = {}
            for item in items:
                merged.update(item)
            return merged

        objects = merge(self.objects, other.objects)
        context_aware_object_factories = merge(
            self.context_aware_object_factories, other.context_aware_object_factories
        )
        return BuildFileAliases(
            objects=objects,
            context_aware_object_factories=context_aware_object_factories,
        )
