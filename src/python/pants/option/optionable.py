# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import functools
import inspect
import re
from abc import ABC, ABCMeta, abstractmethod
from typing import Optional, Type

from pants.engine.selectors import Get
from pants.option.errors import OptionsError
from pants.option.scope import Scope, ScopedOptions, ScopeInfo
from pants.util.meta import classproperty
from pants.util.objects import get_docstring_summary


async def _construct_optionable(optionable_factory):
    scope = optionable_factory.options_scope
    scoped_options = await Get(ScopedOptions, Scope(str(scope)))
    return optionable_factory.optionable_cls(scope, scoped_options.options)


class OptionableFactory(ABC):
    """A mixin that provides a method that returns an @rule to construct subclasses of Optionable.

    Optionable subclasses constructed in this manner must have a particular constructor shape, which
    is loosely defined by `_construct_optionable` and `OptionableFactory.signature`.
    """

    @property
    @abstractmethod
    def optionable_cls(self) -> Type["Optionable"]:
        """The Optionable class that is constructed by this OptionableFactory."""

    @property
    @abstractmethod
    def options_scope(self):
        """The scope from which the ScopedOptions for the target Optionable will be parsed."""

    @classmethod
    def signature(cls):
        """Returns kwargs to construct a `TaskRule` that will construct the target Optionable.

        TODO: This indirection avoids a cycle between this module and the `rules` module.
        """
        partial_construct_optionable = functools.partial(_construct_optionable, cls)

        # NB: We must populate several dunder methods on the partial function because partial functions
        # do not have these defined by default and the engine uses these values to visualize functions
        # in error messages and the rule graph.
        snake_scope = cls.options_scope.replace("-", "_")
        partial_construct_optionable.__name__ = f"construct_scope_{snake_scope}"
        partial_construct_optionable.__module__ = cls.__module__
        _, class_definition_lineno = inspect.getsourcelines(cls)
        partial_construct_optionable.__line_number__ = class_definition_lineno

        return dict(
            output_type=cls.optionable_cls,
            input_selectors=tuple(),
            func=partial_construct_optionable,
            input_gets=(Get.create_statically_for_rule_graph(ScopedOptions, Scope),),
            dependency_optionables=(cls.optionable_cls,),
        )


class Optionable(OptionableFactory, metaclass=ABCMeta):
    """A mixin for classes that can register options on some scope."""

    # Subclasses must override.
    options_scope: Optional[str] = None
    options_scope_category: Optional[str] = None

    # Subclasses may override these to specify a deprecated former name for this Optionable's scope.
    # Option values can be read from the deprecated scope, but a deprecation warning will be issued.
    # The deprecation warning becomes an error at the given Pants version (which must therefore be
    # a valid semver).
    deprecated_options_scope: Optional[str] = None
    deprecated_options_scope_removal_version: Optional[str] = None

    _scope_name_component_re = re.compile(r"^(?:[a-z0-9])+(?:-(?:[a-z0-9])+)*$")

    @classproperty
    def optionable_cls(cls):
        # Fills the `OptionableFactory` contract.
        return cls

    @classmethod
    def is_valid_scope_name_component(cls, s: str) -> bool:
        return s == "" or cls._scope_name_component_re.match(s) is not None

    @classmethod
    def validate_scope_name_component(cls, s: str) -> None:
        if not cls.is_valid_scope_name_component(s):
            raise OptionsError(
                f'Options scope "{s}" is not valid:\nReplace in code with a new scope name consisting of '
                f"dash-separated-words, with words consisting only of lower-case letters and digits."
            )

    @classmethod
    def get_scope_info(cls):
        """Returns a ScopeInfo instance representing this Optionable's options scope."""
        if cls.options_scope is None or cls.options_scope_category is None:
            raise OptionsError(f"{cls.__name__} must set options_scope and options_scope_category.")
        return ScopeInfo(cls.options_scope, cls.options_scope_category, cls)

    @classmethod
    def subscope(cls, scope):
        """Create a subscope under this Optionable's scope."""
        return f"{cls.options_scope}.{scope}"

    @classmethod
    def known_scope_infos(cls):
        """Yields ScopeInfo for all known scopes for this optionable, in no particular order.

        Specific Optionable subtypes may override to provide information about other optionables.
        """
        yield cls.get_scope_info()

    @classmethod
    def get_options_scope_equivalent_flag_component(cls):
        """Return a string representing this optionable's scope as it would be in a command line
        flag.

        This method can be used to generate error messages with flags e.g. to fix some error with a
        pants command. These flags will then be as specific as possible, including e.g. all
        dependent subsystem scopes.
        """
        return re.sub(r"\.", "-", cls.options_scope)

    @classmethod
    def get_description(cls) -> Optional[str]:
        return get_docstring_summary(cls)

    @classmethod
    def register_options(cls, register):
        """Register options for this optionable.

        Subclasses may override and call register(*args, **kwargs).
        """

    @classmethod
    def register_options_on_scope(cls, options):
        """Trigger registration of this optionable's options.

        Subclasses should not generally need to override this method.
        """
        cls.register_options(options.registration_function_for_optionable(cls))

    def __init__(self) -> None:
        # Check that the instance's class defines options_scope.
        # Note: It is a bit odd to validate a class when instantiating an object of it. but checking
        # the class itself (e.g., via metaclass magic) turns out to be complicated, because
        # non-instantiable subclasses (such as TaskBase, Task, Subsystem and other domain-specific
        # intermediate classes) don't define options_scope, so we can only apply this check to
        # instantiable classes. And the easiest way to know if a class is instantiable is to hook into
        # its __init__, as we do here. We usually only create a single instance of an Optionable
        # subclass anyway.
        cls = type(self)
        if not isinstance(cls.options_scope, str):
            raise NotImplementedError(f"{cls} must set an options_scope class-level property.")
