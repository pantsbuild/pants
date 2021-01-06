# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import inspect
import logging
from dataclasses import dataclass
from typing import Any, ClassVar, Iterator, Optional, Set, Tuple, Type, TypeVar, Union, cast

from pants.option.option_value_container import OptionValueContainer
from pants.option.optionable import Optionable, OptionableFactory
from pants.option.scope import GLOBAL_SCOPE, ScopeInfo
from pants.util.ordered_set import OrderedSet

logger = logging.getLogger(__name__)


class SubsystemError(Exception):
    """An error in a subsystem."""


class SubsystemClientError(Exception):
    pass


@dataclass(frozen=True)
class SubsystemDependency(OptionableFactory):
    """Indicates intent to use an instance of `subsystem_cls` scoped to `scope`."""

    subsystem_cls: Type[Optionable]
    scope: str
    removal_version: Optional[Any] = None
    removal_hint: Optional[Any] = None

    def is_global(self):
        return self.scope == GLOBAL_SCOPE

    @property
    def optionable_cls(self):
        # Fills the OptionableFactory contract.
        return self.subsystem_cls

    @property
    def options_scope(self) -> str:
        """The subscope for options of `subsystem_cls` scoped to `scope`.

        This is the scope that option values are read from when initializing the instance indicated
        by this dependency.
        """
        if self.is_global():
            return cast(str, self.subsystem_cls.options_scope)
        else:
            return self.subsystem_cls.subscope(self.scope)


_S = TypeVar("_S", bound="Subsystem")


class Subsystem(Optionable):
    """A separable piece of functionality that may be reused across multiple tasks or other code.

    Subsystems encapsulate the configuration and initialization of things like JVMs,
    Python interpreters, SCMs and so on.

    Set the `help` class property with a description, which will be used in `./pants help`. For the
    best rendering, use soft wrapping (e.g. implicit string concatenation) within paragraphs, but
    hard wrapping (`\n`) to separate distinct paragraphs and/or lists.

    :API: public
    """

    scope: str
    options: OptionValueContainer

    help: ClassVar[str]

    @classmethod
    def is_subsystem_type(cls, obj) -> bool:
        return inspect.isclass(obj) and issubclass(obj, cls)

    @classmethod
    def scoped(cls, optionable, removal_version=None, removal_hint=None) -> SubsystemDependency:
        """Returns a dependency on this subsystem, scoped to `optionable`.

        :param removal_version: An optional deprecation version for this scoped Subsystem dependency.
        :param removal_hint: An optional hint to accompany a deprecation removal_version.

        Return value is suitable for use in Subsystem.subsystem_dependencies().
        """
        return SubsystemDependency(cls, optionable.options_scope, removal_version, removal_hint)

    @classmethod
    def get_scope_info(cls, subscope=None) -> ScopeInfo:
        cls.validate_scope_name_component(cast(str, cls.options_scope))
        if subscope is None:
            return super().get_scope_info()
        else:
            return ScopeInfo(cls.subscope(subscope), cls)

    def __init__(self, scope: str, options: OptionValueContainer) -> None:
        super().__init__()
        self.scope = scope
        self.options = options

    @classmethod
    def subsystem_dependencies(cls) -> Tuple[Union[SubsystemDependency, Type[Subsystem]], ...]:
        """The subsystems this object uses.

        Override to specify your subsystem dependencies. Always add them to your superclass's value.

        Note: Do not call this directly to retrieve dependencies. See subsystem_dependencies_iter().

        :return: A tuple of SubsystemDependency instances.
                 In the common case where you're an optionable and you want to get an instance scoped
                 to you, call subsystem_cls.scoped(cls) to get an appropriate SubsystemDependency.
                 As a convenience, you may also provide just a subsystem_cls, which is shorthand for
                 SubsystemDependency(subsystem_cls, GLOBAL SCOPE) and indicates that we want to use
                 the global instance of that subsystem.
        """
        return tuple()

    @classmethod
    def subsystem_dependencies_iter(cls) -> Iterator[SubsystemDependency]:
        """Iterate over the direct subsystem dependencies of this Optionable."""
        for dep in cls.subsystem_dependencies():
            if isinstance(dep, SubsystemDependency):
                yield dep
            else:
                yield SubsystemDependency(
                    dep, GLOBAL_SCOPE, removal_version=None, removal_hint=None
                )

    @classmethod
    def subsystem_closure_iter(cls) -> Iterator[SubsystemDependency]:
        """Iterate over the transitive closure of subsystem dependencies of this Optionable.

        :raises: :class:`Subsystem.CycleException`
                 if a dependency cycle is detected.
        """
        seen = set()
        dep_path: OrderedSet = OrderedSet()

        def iter_subsystem_closure(subsystem_cls):
            if subsystem_cls in dep_path:
                raise cls.CycleException(list(dep_path) + [subsystem_cls])
            dep_path.add(subsystem_cls)

            for dep in subsystem_cls.subsystem_dependencies_iter():
                if dep not in seen:
                    seen.add(dep)
                    yield dep
                    for d in iter_subsystem_closure(dep.subsystem_cls):
                        yield d

            dep_path.remove(subsystem_cls)

        for dep in iter_subsystem_closure(cls):
            yield dep

    class CycleException(Exception):
        """Thrown when a circular subsystem dependency is detected."""

        def __init__(self, cycle):
            message = "Cycle detected:\n\t{}".format(
                " ->\n\t".join(
                    "{} scope: {}".format(optionable_cls, optionable_cls.options_scope)
                    for optionable_cls in cycle
                )
            )
            super().__init__(message)

    @classmethod
    def known_scope_infos(cls) -> Set[ScopeInfo]:
        """Yield ScopeInfo for all known scopes for this optionable, in no particular order.

        :raises: :class:`Subsystem.CycleException`
                 if a dependency cycle is detected.
        """
        known_scope_infos = set()
        # To check for cycles at the Optionable level, ignoring scope.
        optionables_path: OrderedSet = OrderedSet()

        def collect_scope_infos(optionable_cls, scoped_to, removal_version=None, removal_hint=None):
            if optionable_cls in optionables_path:
                raise cls.CycleException(list(optionables_path) + [optionable_cls])
            optionables_path.add(optionable_cls)

            scope = (
                optionable_cls.options_scope
                if scoped_to == GLOBAL_SCOPE
                else optionable_cls.subscope(scoped_to)
            )
            scope_info = ScopeInfo(
                scope,
                optionable_cls,
                removal_version=removal_version,
                removal_hint=removal_hint,
            )

            if scope_info not in known_scope_infos:
                known_scope_infos.add(scope_info)
                for dep in scope_info.optionable_cls.subsystem_dependencies_iter():
                    # A subsystem always exists at its global scope (for the purpose of options
                    # registration and specification), even if in practice we only use it scoped to
                    # some other scope.
                    #
                    # NB: We do not apply deprecations to this implicit global copy of the scope, because if
                    # the intention was to deprecate the entire scope, that could be accomplished by
                    # deprecating all options in the scope.
                    collect_scope_infos(dep.subsystem_cls, GLOBAL_SCOPE)
                    if not dep.is_global():
                        collect_scope_infos(
                            dep.subsystem_cls,
                            scope,
                            removal_version=dep.removal_version,
                            removal_hint=dep.removal_hint,
                        )

            optionables_path.remove(scope_info.optionable_cls)

        collect_scope_infos(cls, GLOBAL_SCOPE)
        return known_scope_infos

    def __eq__(self, other: Any) -> bool:
        if type(self) != type(other):
            return False
        return bool(self.scope == other.scope and self.options == other.options)
