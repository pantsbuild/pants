# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pants.base.exceptions import TaskError
from pants.binaries.binary_util import BinaryUtil
from pants.subsystem.subsystem import Subsystem
from pants.util.memo import memoized_method, memoized_property


class BinaryToolBase(Subsystem):
  """Base class for subsytems that configure binary tools.

  Subclasses can be further subclassed, manually, e.g., to add any extra options.

  :API: public
  """
  # Subclasses must set these to appropriate values for the tool they define.
  # They must also set options_scope to the tool name as understood by BinaryUtil.
  support_subdir = None
  platform_dependent = None
  archive_type = None
  default_version = None

  # Subclasses may set these to effect migration from an old --version option to this one.
  # TODO(benjy): Remove these after migration to the mixin is complete.
  replaces_scope = None
  replaces_name = None

  # Subclasses may set this to provide extra register() kwargs for the --version option.
  extra_version_option_kwargs = None

  class InvalidSupportDir(TaskError):
    """Indicates that the subclass of BinaryToolBase did not set up a valid
    supportdir to pass to BinaryUtil."""
    pass

  @classmethod
  def subsystem_dependencies(cls):
    return super(BinaryToolBase, cls).subsystem_dependencies() + (
      BinaryUtil.Factory,
    )

  @classmethod
  def register_options(cls, register):
    super(BinaryToolBase, cls).register_options(register)

    version_registration_kwargs = {
      'type': str,
      'default': cls.default_version,
    }
    if cls.extra_version_option_kwargs:
      version_registration_kwargs.update(cls.extra_version_option_kwargs)
    version_registration_kwargs['help'] = (
      version_registration_kwargs.get('help') or
      'Version of the {} {} to use'.format(cls.options_scope,
                                           'binary' if cls.platform_dependent else 'script')
    )
    # The default for fingerprint in register() is False, but we want to default to True.
    if 'fingerprint' not in version_registration_kwargs:
      version_registration_kwargs['fingerprint'] = True
    register('--version', **version_registration_kwargs)

  def select(self, context=None):
    """Returns the path to the specified binary tool.

    If replaces_scope and replaces_name are defined, then the caller must pass in
    a context, otherwise no context should be passed.

    # TODO: Once we're migrated, get rid of the context arg.

    :API: public
    """
    version = self.get_options().version
    if self.replaces_scope and self.replaces_name:
      # If the old option is provided explicitly, let it take precedence.
      old_opts = context.options.for_scope(self.replaces_scope)
      if not old_opts.is_default(self.replaces_name):
        version = old_opts.get(self.replaces_name)
    return self._select_for_version(version)

  @memoized_property
  def _binary_util(self):
    return BinaryUtil.Factory.create()

  # can override this and call super() to compose
  @classmethod
  def support_dir_paths(cls):
    return []

  @classmethod
  def _support_dir(cls):
    paths = cls.support_dir_paths()
    if len(paths) == 0:
      raise self.InvalidSupportDir(
        'support_dir_paths() must be a non-empty list of directory paths '
        'to join!'
      )
    subdir = cls.support_subdir or cls.options_scope
    paths.append(subdir)
    return os.path.join(*paths)

  @memoized_method
  def _select_for_version(self, version):
    return self._binary_util.select(
      self._support_dir(),
      version,
      self.options_scope,
      self.platform_dependent,
      self.archive_type)


class NativeTool(BinaryToolBase):
  """A base class for native-code tools.

  :API: public
  """
  platform_dependent = True

  @classmethod
  def support_dir_paths(cls):
    return super(NativeTool, cls).support_dir_paths() + ['bin']


class Script(BinaryToolBase):
  """A base class for platform-independent scripts.

  :API: public
  """
  platform_dependent = False

  @classmethod
  def support_dir_paths(cls):
    return super(Script, cls).support_dir_paths() + ['scripts']
