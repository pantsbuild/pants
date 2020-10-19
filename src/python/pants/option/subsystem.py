# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import importlib
import inspect
import logging
from dataclasses import dataclass
from typing import (
    Any,
    Callable,
    ClassVar,
    Dict,
    Iterable,
    List,
    Optional,
    Tuple,
    Type,
    TypeVar,
    Union,
    cast,
)

from pants.option.option_value_container import OptionValueContainer
from pants.option.optionable import Optionable, OptionableFactory
from pants.option.options import Options
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

    subsystem_cls: Any
    scope: Any
    removal_version: Optional[Any] = None
    removal_hint: Optional[Any] = None

    def is_global(self):
        return self.scope == GLOBAL_SCOPE

    @property
    def optionable_cls(self):
        # Fills the OptionableFactory contract.
        return self.subsystem_cls

    @property
    def options_scope(self):
        """The subscope for options of `subsystem_cls` scoped to `scope`.

        This is the scope that option values are read from when initializing the instance indicated
        by this dependency.
        """
        if self.is_global():
            return self.subsystem_cls.options_scope
        else:
            return self.subsystem_cls.subscope(self.scope)


_S = TypeVar("_S", bound="Subsystem")


class Subsystem(Optionable):
    """A separable piece of functionality that may be reused across multiple tasks or other code.

    Subsystems encapsulate the configuration and initialization of things like JVMs,
    Python interpreters, SCMs and so on.

    Subsystem instances can be global or per-optionable. Global instances are useful for representing
    global concepts, such as the SCM used in the workspace. Per-optionable instances allow individual
    Optionable objects (notably, tasks) to have their own configuration for things such as artifact
    caches.

    Each subsystem type has an option scope. The global instance of that subsystem initializes
    itself from options in that scope. An optionable-specific instance initializes itself from options
    in an appropriate subscope, which defaults back to the global scope.

    For example, the global artifact cache options would be in scope `cache`, but the
    compile.java task can override those options in scope `cache.compile.java`.

    Subsystems may depend on other subsystems.

    :API: public
    """

    scope: str
    options: OptionValueContainer

    # TODO: The full Options object for this pants run for use by `global_instance` and
    # `scoped_instance`.
    _options: ClassVar[Optional[Options]] = None

    # TODO: A cache of (cls, scope) -> the instance of cls tied to that scope.
    # NB: it would be ideal to use `_S` rather than `Subsystem`, but we can't do this because
    # MyPy complains that `_S` would not be properly constrained. Specifically, it suggests that we'd
    # have to use typing.Generic or typing.Protocol to properly constrain the type var, which we
    # don't want to do.
    _scoped_instances: ClassVar[Dict[Tuple[Type["Subsystem"], str], "Subsystem"]] = {}

    class UninitializedSubsystemError(SubsystemError):
        def __init__(self, class_name, scope):
            super().__init__(f'Subsystem "{class_name}" not initialized for scope "{scope}"')

    @classmethod
    def is_subsystem_type(cls, obj):
        return inspect.isclass(obj) and issubclass(obj, cls)

    @classmethod
    def scoped(cls, optionable, removal_version=None, removal_hint=None):
        """Returns a dependency on this subsystem, scoped to `optionable`.

        :param removal_version: An optional deprecation version for this scoped Subsystem dependency.
        :param removal_hint: An optional hint to accompany a deprecation removal_version.

        Return value is suitable for use in Subsystem.subsystem_dependencies().
        """
        return SubsystemDependency(cls, optionable.options_scope, removal_version, removal_hint)

    @classmethod
    def get_scope_info(cls, subscope=None):
        cls.validate_scope_name_component(cls.options_scope)
        if subscope is None:
            return super().get_scope_info()
        else:
            return ScopeInfo(cls.subscope(subscope), cls)

    @classmethod
    def set_options(cls, options: Options) -> None:
        cls._options = options

    @classmethod
    def is_initialized(cls) -> bool:
        return cls._options is not None

    @classmethod
    def global_instance(cls: Type[_S]) -> _S:
        """Returns the global instance of this subsystem.

        :API: public

        :returns: The global subsystem instance.

        Note that `global_instance` is a v1-idiom only. v2 rules should always request a subsystem as a rule input, rather than
        trying to call <subsystem>.global_instance() in the body of an `@rule`.
        """
        return cls._instance_for_scope(cls.options_scope)  # type: ignore[arg-type]  # MyPy is treating cls.options_scope as a Callable, rather than `str`

    @classmethod
    def scoped_instance(cls: Type[_S], optionable: Union[Optionable, Type[Optionable]]) -> _S:
        """Returns an instance of this subsystem for exclusive use by the given `optionable`.

        :API: public

        :param optionable: An optionable type or instance to scope this subsystem under.
        :returns: The scoped subsystem instance.
        """
        if not isinstance(optionable, Optionable) and not issubclass(optionable, Optionable):
            raise TypeError(
                "Can only scope an instance against an Optionable, given {} of type {}.".format(
                    optionable, type(optionable)
                )
            )
        return cls._instance_for_scope(cls.subscope(optionable.options_scope))

    @classmethod
    def _instance_for_scope(cls: Type[_S], scope: str) -> _S:
        if cls._options is None:
            raise cls.UninitializedSubsystemError(cls.__name__, scope)
        key = (cls, scope)
        if key not in cls._scoped_instances:
            cls._scoped_instances[key] = cls(scope, cls._options.for_scope(scope))
        return cast(_S, cls._scoped_instances[key])

    @classmethod
    def reset(cls, reset_options: bool = True) -> None:
        """Forget all option values and cached subsystem instances.

        Used primarily for test isolation and to reset subsystem state for pantsd.
        """
        if reset_options:
            cls._options = None
        cls._scoped_instances = {}

    def __init__(self, scope: str, options: OptionValueContainer) -> None:
        super().__init__()
        self.scope = scope
        self.options = options

    @staticmethod
    def get_streaming_workunit_callbacks(subsystem_names: Iterable[str]) -> List[Callable]:
        """This method is used to dynamically generate a list of callables intended to be passed to
        StreamingWorkunitHandler. The caller provides a collection of strings representing a Python
        import path to a class that implements the `Subsystem` class. It will then inspect these
        classes for the presence of a special method called `handle_workunits`, which will.

        be called with a set of kwargs - see the docstring for StreamingWorkunitHandler.

        For instance, you might invoke this method with something like:

        `Subsystem.get_streaming_workunit_callbacks(["pants.reporting.workunits.Workunit"])`

        And this will result in the method attempting to dynamically-import a
        module called "pants.reporting.workunits", inspecting it for the presence
        of a class called `Workunit`, getting a global instance of this Subsystem,
        and returning a list containing a single reference to the
        `handle_workunits` method defined on it - and returning an empty list and
        emitting warnings if any of these steps fail.
        """

        callables = []

        for name in subsystem_names:
            try:
                name_components = name.split(".")
                module_name = ".".join(name_components[:-1])
                class_name = name_components[-1]
                module = importlib.import_module(module_name)
                subsystem_class = getattr(module, class_name)
            except (IndexError, AttributeError, ModuleNotFoundError, ValueError) as e:
                logger.warning(f"Invalid module name: {name}: {e}")
                continue
            except ImportError as e:
                logger.warning(f"Could not import {module_name}: {e}")
                continue
            try:
                subsystem = subsystem_class.global_instance()
            except AttributeError:
                logger.warning(f"{subsystem_class} is not a global subsystem.")
                continue

            try:
                callables.append(subsystem.handle_workunits)
            except AttributeError:
                logger.warning(
                    f"{subsystem_class} does not have a method named `handle_workunits` defined."
                )
                continue

        return callables

    @classmethod
    def subsystem_dependencies(cls):
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
    def subsystem_dependencies_iter(cls):
        """Iterate over the direct subsystem dependencies of this Optionable."""
        for dep in cls.subsystem_dependencies():
            if isinstance(dep, SubsystemDependency):
                yield dep
            else:
                yield SubsystemDependency(
                    dep, GLOBAL_SCOPE, removal_version=None, removal_hint=None
                )

    @classmethod
    def subsystem_closure_iter(cls):
        """Iterate over the transitive closure of subsystem dependencies of this Optionable.

        :rtype: :class:`collections.Iterator` of :class:`SubsystemDependency`
        :raises: :class:`Subsystem.CycleException`
                 if a dependency cycle is detected.
        """
        seen = set()
        dep_path = OrderedSet()

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
    def known_scope_infos(cls):
        """Yield ScopeInfo for all known scopes for this optionable, in no particular order.

        :rtype: set of :class:`pants.option.scope.ScopeInfo`
        :raises: :class:`Subsystem.CycleException`
                 if a dependency cycle is detected.
        """
        known_scope_infos = set()
        optionables_path = (
            OrderedSet()
        )  # To check for cycles at the Optionable level, ignoring scope.

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
