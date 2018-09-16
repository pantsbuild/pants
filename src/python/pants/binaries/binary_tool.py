# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import logging
import os
from builtins import str

from future.utils import text_type

from pants.binaries.binary_util import BinaryRequest, BinaryUtil
from pants.engine.fs import PathGlobs, PathGlobsAndRoot
from pants.fs.archive import XZCompressedTarArchiver, create_archiver
from pants.subsystem.subsystem import Subsystem
from pants.util.memo import memoized_method, memoized_property


logger = logging.getLogger(__name__)


# TODO: Add integration tests for this file.
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
    sub_deps = super(BinaryToolBase, cls).subsystem_dependencies() + (BinaryUtil.Factory,)

    # TODO: if we need to do more conditional subsystem dependencies, do it declaratively with a
    # dict class field so that we only try to create or access it if we declared a dependency on it.
    if cls.archive_type == 'txz':
      sub_deps = sub_deps + (XZ.scoped(cls),)

    return sub_deps

  @memoized_property
  def _xz(self):
    if self.archive_type == 'txz':
      return XZ.scoped_instance(self)
    return None

  @memoized_method
  def _get_archiver(self):
    if not self.archive_type:
      return None

    # This forces downloading and extracting the `XZ` archive if any BinaryTool with a 'txz'
    # archive_type is used, but that's fine, because unless the cache is manually changed we won't
    # do more work than necessary.
    if self.archive_type == 'txz':
      return self._xz.tar_xz_extractor

    return create_archiver(self.archive_type)

  def get_external_url_generator(self):
    """Override and return an instance of BinaryToolUrlGenerator to download from those urls.

    If this method returns None, urls to download the tool will be constructed from
    --binaries-baseurls. Otherwise, generate_urls() will be invoked on the result with the requested
    version and host platform.

    If the bootstrap option --allow-external-binary-tool-downloads is False, the result of this
    method will be ignored. Implementations of BinaryTool must be aware of differences (e.g., in
    archive structure) between the external and internal versions of the downloaded tool, if any.

    See the :class:`LLVM` subsystem for an example of usage.
    """
    return None

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
      if context:
        # If the old option is provided explicitly, let it take precedence.
        old_opts = context.options.for_scope(self.replaces_scope)
        if old_opts.get(self.replaces_name) and not old_opts.is_default(self.replaces_name):
          return old_opts.get(self.replaces_name)
      else:
        logger.warn('Cannot resolve version of {} from deprecated option {} in scope {} without a '
                    'context!'.format(self._get_name(), self.replaces_name, self.replaces_scope))
    return self.get_options().version

  @memoized_property
  def _binary_util(self):
    return BinaryUtil.Factory.create()

  @classmethod
  def _get_name(cls):
    return cls.name or cls.options_scope

  @classmethod
  def get_support_dir(cls):
    return 'bin/{}'.format(cls._get_name())

  @classmethod
  def _name_to_fetch(cls):
    return '{}{}'.format(cls._get_name(), cls.suffix)

  def _make_binary_request(self, version):
    return BinaryRequest(
      supportdir=self.get_support_dir(),
      version=version,
      name=self._name_to_fetch(),
      platform_dependent=self.platform_dependent,
      external_url_generator=self.get_external_url_generator(),
      archiver=self._get_archiver())

  def _select_for_version(self, version):
    binary_request = self._make_binary_request(version)
    return self._binary_util.select(binary_request)


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

  def hackily_snapshot(self, context):
    bootstrapdir = self.get_options().pants_bootstrapdir
    script_relpath = os.path.relpath(self.select(context), bootstrapdir)
    snapshot = context._scheduler.capture_snapshots((
      PathGlobsAndRoot(
        PathGlobs((script_relpath,)),
        text_type(bootstrapdir),
      ),
    ))[0]
    return (script_relpath, snapshot)


class XZ(NativeTool):
  options_scope = 'xz'
  default_version = '5.2.4-3'
  archive_type = 'tgz'

  @memoized_property
  def tar_xz_extractor(self):
    return XZCompressedTarArchiver(self._executable_location())

  def _executable_location(self):
    return os.path.join(self.select(), 'bin', 'xz')
