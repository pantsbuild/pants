# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.binaries.binary_util import BinaryUtil
from pants.subsystem.subsystem import Subsystem


class BinaryToolBase(Subsystem):
  """Base class for subsytems that configure binary tools.

  Typically, a specific subclass is created via create_binary_tool_subsystem_cls() below.
  That subclass can be further subclassed, manually, e.g., to add any extra options.
  """
  # Subclasses must set these to appropriate values for the tool they define.
  # They must also, of course, set options_scope appropriately (typically the name of the
  # tool, but this is not a requirement).
  support_dir = None
  platform_dependent = None
  default_version = None

  # Subclasses may set these to effect migration from an old --version option to this one.
  # TODO(benjy): Remove these after migration to the mixin is complete.
  replaces_scope = None
  replaces_name = None

  # Subclasses may set this to provide extra register() kwargs for the --version option.
  extra_version_option_kwargs = None

  @classmethod
  def register_options(cls, register):
    version_registration_kwargs = {
      'type': str,
      'default': cls.default_version,
    }
    if cls.extra_version_option_kwargs:
      version_registration_kwargs.update(cls.extra_version_option_kwargs)
    version_registration_kwargs['help'] = (
      version_registration_kwargs['help'] or
      'Version of the {} {} to use'.format(cls.name,
                                           'binary' if cls.platform_dependent else 'script')
    )
    # The default for fingerprint in register() is False, but we want to default to True.
    if 'fingerprint' not in version_registration_kwargs:
      version_registration_kwargs['fingerprint'] = True
    register('--version', **version_registration_kwargs)

  def select(self):
    version = self.get_options().version
    if self.replaces_scope and self.replaces_name:
      # If the old option is provided explicitly, let it take precedence.
      old_opts = self.context.options.for_scope(self.replaces_scope)
      if not old_opts.is_default(self.replaces_name):
        version = old_opts.get(self.replaces_name)
    return BinaryUtil.Factory.create().select(
      self.supportdir, version, self.name, self.platform_dependent)


def create_binary_tool_subsystem_cls(
    tool_name,
    supportdir,
    platform_dependent,
    default_version,
    fingerprint=True,
    help=None,
    removal_version=None,
    removal_hint=None,
    # Temporary params, while migrating existing version options.
    replaces_scope=None,
    replaces_name=None):
  """A factory for creating BinaryToolBase subclasses."""
  return type(
    b'{}BinaryTool'.format(tool_name.title()),
    (BinaryToolBase,),
    {
      b'extra_version_option_kwargs': {
        'fingerprint': fingerprint,
        'help': help,
        'removal_version': removal_version,
        'removal_hint': removal_hint,
      },
      b'options_scope': tool_name,
      b'name': tool_name,
      b'support_dir': supportdir,
      b'platform_dependent': platform_dependent,
      b'default_version': default_version,

      b'replaces_scope': replaces_scope,
      b'replaces_name': replaces_name,
    }
  )