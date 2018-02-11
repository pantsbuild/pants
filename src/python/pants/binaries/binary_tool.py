# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.binaries.binary_util import BinaryUtil
from pants.subsystem.subsystem import Subsystem


class BinaryToolBase(Subsystem):
  # Subclasses must set this to the register() kwargs for the --version option.
  version_registration_kwargs = None
  # Subclasses must set these to appropriate values for the tool they define.
  support_dir = None
  platform_dependent = None
  replaces_scope = None
  replaces_name = None

  @classmethod
  def register_options(cls, register):
    register('--version', **cls.version_registration_kwargs)

  def select(self):
    version = self.get_options().version
    if self.replaces_scope and self.replaces_name:
      # If the old option is provided explicitly, let it take precedence.
      old_opts = self.context.options.for_scope(self.replaces_scope)
      if not old_opts.is_default(self.replaces_name):
        version = old_opts.get(self.replaces_name)
    return BinaryUtil.Factory.create().select(
      self.supportdir, version, self.name, self.platform_dependent)


def create_binary_tool_cls(supportdir,
                           name,
                           default_version,
                           platform_dependent,
                           fngerprint=True,
                           help=None,
                           removal_version=None,
                            removal_hint=None,
                            # Temporary params, while migrating existing version options.
                            replaces_scope=None,
                            replaces_name=None):
  """A factory for creating BinaryToolBase subclasses."""
  help = help or 'Version of the {} {} to use'.format(
    name, 'binary' if platform_dependent else 'script')
  return type(b'{}BinaryTool'.format(name), (BinaryToolBase,), {
    b'version_registration_kwargs': {
      'default_version': default_version,
      'fingerprint': fingerprint,
      'help': help,
      'removal_version': removal_version,
      'removal_hint': removal_hint,
    },
    b'support_dir': supportdir,
    b'name': name,
    b'platform_dependent': platform_dependent,
    b'replaces_scope': replaces_scope,
    b'replaces_name': replaces_name,
  })