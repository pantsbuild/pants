# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from abc import abstractmethod, abstractproperty

from future.utils import text_type

from pants.util.memo import memoized_property
from pants.util.meta import AbstractClass
from pants.util.objects import datatype


class MirroredTargetOptionDeclaration(AbstractClass):
  """An interface for operations to perform on an option which may also be set on a target."""

  @abstractproperty
  def is_flagged(self):
    """Whether the option was specified on the command line."""

  @abstractmethod
  def extract_target_value(self, target):
    """Get the value of this option from target. May return None if not set on the target."""

  @abstractproperty
  def option_value(self):
    """Get the value of this option, separate from any target."""

  def get_mirrored_scalar_option_value(self, target):
    # Options specified on the command line take precedence over anything else.
    if self.is_flagged:
      return self.option_value

    # Retrieve the value from the target, if set.
    target_setting = self.extract_target_value(target)
    if target_setting is not None:
      return target_setting

    # Otherwise, retrieve the value from the environment/pants.ini/hardcoded default.
    return self.option_value


class OptionableMirroredOptionDeclaration(MirroredTargetOptionDeclaration):
  """Partial implementation of MirroredTargetOptionDeclaration for an OptionValueContainer."""

  @abstractproperty
  def options(self):
    """Return an instance of OptionValueContainer or something compatible with its API."""

  @abstractproperty
  def option_name(self):
    """Return the option name to access `self.options` with."""

  @property
  def is_flagged(self):
    return self.options.is_flagged(self.option_name)

  @property
  def option_value(self):
    return self.options.get(self.option_name)


class OptionableTargetFieldDeclaration(datatype([
    'options',
    ('option_name', text_type),
    'target_field_name',
]), OptionableMirroredOptionDeclaration):
  """A MirroredTargetOptionDeclaration which accesses the target by field name."""

  def extract_target_value(self, target):
    return getattr(target, self.target_field_name)


class OptionableTargetAccessorDeclaration(datatype([
    'options',
    ('option_name', text_type),
    'accessor',
]), OptionableMirroredOptionDeclaration):
  """A MirroredTargetOptionDeclaration which uses a custom accessor method for the target value."""

  def extract_target_value(self, target):
    return self.accessor(target)


class MirroredTargetOptionMixin(AbstractClass):
  """Get option values which may be set in this subsystem or in a Target's keyword argument."""

  # TODO: support list/set options in addition to scalars!
  @abstractproperty
  def mirrored_target_option_actions(self):
    """Subclasses should override and return a dict of (subsystem option name) -> "selector".

    A selector is either:
    - a string => access that property on the target with getattr().
    - a function => return the result of that function called on the target.

    This property should return a dict mapping this subsystem's options attribute name (with
    underscores) to the corresponding selector.
    """

  @memoized_property
  def _mirrored_option_declarations(self):
    ret = {}
    for option_name, accessor_spec in self.mirrored_target_option_actions.items():
      if isinstance(accessor_spec, text_type):
        # If the selector is a string, access the target by its field of that name.
        declaration = OptionableTargetFieldDeclaration(
          options=self.get_options(),
          option_name=option_name,
          target_field_name=accessor_spec,
        )
      else:
        # If the selector is anything else, assume it's a unary method.
        declaration = OptionableTargetAccessorDeclaration(
          options=self.get_options(),
          option_name=option_name,
          accessor=accessor_spec,
        )
      ret[option_name] = declaration
    return ret

  def get_scalar_mirrored_target_option(self, option_name, target):
    """Get the attribute `field_name` from `target` if set, else from this subsystem's options."""
    mirrored_option_declaration = self._mirrored_option_declarations[option_name]
    return mirrored_option_declaration.get_mirrored_scalar_option_value(target)
