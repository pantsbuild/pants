# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from abc import abstractmethod, abstractproperty

from future.utils import text_type

from pants.option.optionable import Optionable
from pants.util.memo import memoized_property
from pants.util.meta import AbstractClass, classproperty
from pants.util.objects import SubclassesOf, datatype


class MirroredTargetOptionDeclaration(AbstractClass):
  """???"""

  @abstractproperty
  def is_flagged(self):
    """???"""

  @abstractmethod
  def extract_target_value(self, target):
    """???"""

  @abstractproperty
  def option_value(self):
    """???"""

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


class BasicMirroredTargetOption(datatype([
    ('optionable', SubclassesOf(Optionable)),
    ('option_name', text_type),
    ('target_field_name', text_type),
]), MirroredTargetOptionDeclaration):

  @property
  def _options(self):
    return self.optionable.get_options()

  @property
  def is_flagged(self):
    # import pdb; pdb.set_trace()
    return self._options.is_flagged(self.option_name)

  def extract_target_value(self, target):
    return getattr(target, self.target_field_name)

  @property
  def option_value(self):
    return self._options.get(self.option_name)


# TODO: consider coalescing existing methods of mirroring options between a target and a subsystem
# -- see pants.backend.jvm.subsystems.dependency_context.DependencyContext#defaulted_property()!
class MirroredTargetOptionMixin(AbstractClass):
  """Get option values which may be set in this subsystem or in a Target's keyword argument."""

  # TODO: support list/set options in addition to scalars!
  @classproperty
  @abstractmethod
  def mirrored_option_to_kwarg_map(cls):
    """Subclasses should override and return a dict of (subsystem option name) -> (target kwarg).

    This classproperty should return a dict mapping this subsystem's options attribute name (with
    underscores) to the corresponding target's keyword argument name.
    """

  @memoized_property
  def _mirrored_option_declarations(self):
    return {
      option_name: BasicMirroredTargetOption(
        optionable=self,
        option_name=option_name,
        target_field_name=target_field_name,
      )
      for option_name, target_field_name in self.mirrored_option_to_kwarg_map.items()
    }

  def get_target_mirrored_option(self, option_name, target):
    """Get the attribute `field_name` from `target` if set, else from this subsystem's options."""
    mirrored_option_declaration = self._mirrored_option_declarations[option_name]
    return mirrored_option_declaration.get_mirrored_scalar_option_value(target)
