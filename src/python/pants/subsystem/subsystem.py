# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import importlib
import inspect
import logging
from typing import Callable, Dict, Iterable, List, Optional, Tuple, Type, TypeVar, Union, cast

from pants.option.option_value_container import OptionValueContainer
from pants.option.optionable import Optionable
from pants.option.options import Options
from pants.option.scope import ScopeInfo
from pants.subsystem.subsystem_client_mixin import SubsystemClientMixin, SubsystemDependency

logger = logging.getLogger(__name__)


class SubsystemError(Exception):
    """An error in a subsystem."""


_S = TypeVar("_S", bound="Subsystem")


class Subsystem(SubsystemClientMixin, Optionable):
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

    Subsystems may depend on other subsystems, and therefore mix in SubsystemClientMixin.

    :API: public
    """

    options_scope_category = ScopeInfo.SUBSYSTEM

    class UninitializedSubsystemError(SubsystemError):
        def __init__(self, class_name, scope):
            super().__init__(
                f'Subsystem "{class_name}" not initialized for scope "{scope}". Is subsystem missing '
                "from subsystem_dependencies() in a task? "
            )

    @classmethod
    def is_subsystem_type(cls, obj):
        return inspect.isclass(obj) and issubclass(obj, cls)

    @classmethod
    def scoped(cls, optionable, removal_version=None, removal_hint=None):
        """Returns a dependency on this subsystem, scoped to `optionable`.

        :param removal_version: An optional deprecation version for this scoped Subsystem dependency.
        :param removal_hint: An optional hint to accompany a deprecation removal_version.

        Return value is suitable for use in SubsystemClientMixin.subsystem_dependencies().
        """
        return SubsystemDependency(cls, optionable.options_scope, removal_version, removal_hint)

    @classmethod
    def get_scope_info(cls, subscope=None):
        cls.validate_scope_name_component(cls.options_scope)
        if subscope is None:
            return super().get_scope_info()
        else:
            return ScopeInfo(cls.subscope(subscope), ScopeInfo.SUBSYSTEM, cls)

    # The full Options object for this pants run.  Will be set after options are parsed.
    # TODO: A less clunky way to make option values available?
    _options: Optional[Options] = None

    @classmethod
    def set_options(cls, options: Options) -> None:
        cls._options = options

    @classmethod
    def is_initialized(cls) -> bool:
        return cls._options is not None

    # A cache of (cls, scope) -> the instance of cls tied to that scope.
    # NB: it would be ideal to use `_S` rather than `Subsystem`, but we can't do this because
    # MyPy complains that `_S` would not be properly constrained. Specifically, it suggests that we'd
    # have to use typing.Generic or typing.Protocol to properly constrain the type var, which we
    # don't want to do.
    _scoped_instances: Dict[Tuple[Type["Subsystem"], str], "Subsystem"] = {}

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

    def __init__(self, scope: str, scoped_options: OptionValueContainer) -> None:
        """Note: A subsystem has no access to options in scopes other than its own.

    TODO: We'd like that to be true of Tasks some day. Subsystems will help with that.

    Code should call scoped_instance() or global_instance() to get a subsystem instance.
    It should not invoke this constructor directly.

    :API: public
    """
        super().__init__()
        self._scope = scope
        self._scoped_options = scoped_options
        self._fingerprint = None

    # It's safe to override the signature from Optionable because we validate
    # that every Optionable has `options_scope` defined as a `str` in the __init__. This code is
    # complex, though, and may be worth refactoring.
    @property
    def options_scope(self) -> str:  # type: ignore[override]
        return self._scope

    @property
    def options(self) -> OptionValueContainer:
        """Returns the option values for this subsystem's scope.

        :API: public
        """
        return self._scoped_options

    def get_options(self) -> OptionValueContainer:
        """Returns the option values for this subsystem's scope.

        :API: public
        """
        return self._scoped_options

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
