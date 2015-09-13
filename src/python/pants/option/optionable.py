# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from six import string_types

from pants.option.errors import OptionsError
from pants.option.scope import ScopeInfo
from pants.util.meta import AbstractClass


class Optionable(AbstractClass):
  """A mixin for classes that can register options on some scope."""

  # Subclasses must override.
  options_scope = None
  options_scope_category = None

  @classmethod
  def get_scope_info(cls):
    """Returns a ScopeInfo instance representing this Optionable's options scope."""
    if cls.options_scope is None or cls.options_scope_category is None:
      raise OptionsError(
        '{} must set options_scope and options_scope_category.'.format(cls.__name__))
    return ScopeInfo(cls.options_scope, cls.options_scope_category, cls)

  @classmethod
  def get_description(cls):
    # First line of docstring.
    return '' if cls.__doc__ is None else cls.__doc__.partition('\n')[0]

  @classmethod
  def register_options(cls, register):
    """Register options for this optionable.

    Subclasses may override and call register(*args, **kwargs) with argparse arguments.
    """

  @classmethod
  def register_options_on_scope(cls, options):
    """Trigger registration of this optionable's options.

    Subclasses should not generally need to override this method.
    """
    cls.register_options(options.registration_function_for_optionable(cls))

  def __init__(self):
    # Check that the instance's class defines options_scope.
    # Note: It is a bit odd to validate a class when instantiating an object of it. but checking
    # the class itself (e.g., via metaclass magic) turns out to be complicated, because
    # non-instantiable subclasses (such as TaskBase, Task, Subsystem and other domain-specific
    # intermediate classes) don't define options_scope, so we can only apply this check to
    # instantiable classes. And the easiest way to know if a class is instantiable is to hook into
    # its __init__, as we do here. We usually only create a single instance of an Optionable
    # subclass anyway.
    cls = type(self)
    if not isinstance(cls.options_scope, string_types):
      raise NotImplementedError('{} must set an options_scope class-level property.'.format(cls))
