# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.binaries.binary_util import BinaryUtil
from pants.subsystem.subsystem import Subsystem
from pants.util.memo import memoized_method, memoized_property


class BinaryToolBase(Subsystem):
  """Base class for subsytems that configure binary tools.

  Subclasses can be further subclassed, manually, e.g., to add any extra options.

  :API: public
  """
  # Subclasses must set these to appropriate values for the tool they define.
  # They must also set options_scope appropriately.
  platform_dependent = None
  archive_type = None  # See pants.fs.archive.archive for valid string values.
  default_version = None

  # Subclasses may set this to the tool name as understood by BinaryUtil.
  # If unset, it defaults to the value of options_scope.
  name = None

  # Subclasses may set this to a suffix (e.g., '.pex') to add to the computed remote path.
  # Note that setting archive_type will add an appropriate archive suffix after this suffix.
  suffix = ''

  # Subclasses may set these to effect migration from an old --version option to this one.
  # TODO(benjy): Remove these after migration to the mixin is complete.
  replaces_scope = None
  replaces_name = None

  # Subclasses may set this to provide extra register() kwargs for the --version option.
  extra_version_option_kwargs = None

  @classmethod
  def subsystem_dependencies(cls):
    return super(BinaryToolBase, cls).subsystem_dependencies() + (BinaryUtil.Factory,)

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
      'Version of the {} {} to use'.format(cls._get_name(),
                                           'binary' if cls.platform_dependent else 'script')
    )
    # The default for fingerprint in register() is False, but we want to default to True.
    if 'fingerprint' not in version_registration_kwargs:
      version_registration_kwargs['fingerprint'] = True
    register('--version', **version_registration_kwargs)

  @memoized_method
  def select(self, context=None):
    """Returns the path to the specified binary tool.

    If replaces_scope and replaces_name are defined, then the caller must pass in
    a context, otherwise no context should be passed.

    # TODO: Once we're migrated, get rid of the context arg.

    :API: public
    """
    return self._select_for_version(self.version(context))

  @memoized_method
  def version(self, context=None):
    """Returns the version of the specified binary tool.

    If replaces_scope and replaces_name are defined, then the caller must pass in
    a context, otherwise no context should be passed.

    # TODO: Once we're migrated, get rid of the context arg.

    :API: public
    """
    if self.replaces_scope and self.replaces_name:
      # If the old option is provided explicitly, let it take precedence.
      old_opts = context.options.for_scope(self.replaces_scope)
      if old_opts.get(self.replaces_name) and not old_opts.is_default(self.replaces_name):
        return old_opts.get(self.replaces_name)
    return self.get_options().version

  @memoized_property
  def _binary_util(self):
    return BinaryUtil.Factory.create()

  @classmethod
  def get_support_dir(cls):
    return 'bin/{}'.format(cls._get_name())

  @memoized_method
  def _select_for_version(self, version):
    return self._binary_util.select(
      supportdir=self.get_support_dir(),
      version=version,
      name='{}{}'.format(self._get_name(), self.suffix),
      platform_dependent=self.platform_dependent,
      archive_type=self.archive_type)

  @classmethod
  def _get_name(cls):
    return cls.name or cls.options_scope


class NativeTool(BinaryToolBase):
  """A base class for native-code tools.

  :API: public
  """
  platform_dependent = True


class Script(BinaryToolBase):
  """A base class for platform-independent scripts.

  :API: public
  """
  platform_dependent = False
