# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from builtins import object

from pants.util.meta import classproperty


# TODO: consider coalescing existing methods of mirroring options between a target and a subsystem
# -- see pants.backend.jvm.subsystems.dependency_context.DependencyContext#defaulted_property()!
class MirroredTargetOptionMixin(object):
  """Get option values which may be set in this subsystem or in a Target's keyword argument."""

  @classproperty
  def mirrored_option_to_kwarg_map(cls):
    """Subclasses should override and return a dict of (subsystem option name) -> (target kwarg).

    This classproperty should return a dict mapping this subsystem's options attribute name (with
    underscores) to the corresponding target's keyword argument name.
    """
    raise NotImplementedError()

  def get_target_mirrored_option(self, option_name, target):
    field_name = self.mirrored_option_to_kwarg_map[option_name]
    return self._get_subsystem_target_mirrored_field_value(option_name, field_name, target)

  def _get_subsystem_target_mirrored_field_value(self, option_name, field_name, target):
    """Get the attribute `field_name` from `target` if set, else from this subsystem's options."""
    tgt_setting = getattr(target, field_name)
    if tgt_setting is None:
      return getattr(self.get_options(), option_name)
    return tgt_setting
