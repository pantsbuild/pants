# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE)

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import os
from xml.dom.minidom import parse

from pants.base.payload import JvmTargetPayload
from pants.base.target import Target


class AndroidTarget(Target):
  """A base class for all Android targets."""

  # Missing attributes from the AndroidManifest would eventually error in the compilation process.
  # But since the error would raise here in the target definition, we are catching the exception
  class BadManifestError(Exception):
    """Indicates an invalid android manifest."""


  def __init__(self,
               address=None,
               sources=None,
               sources_rel_path=None,
               excludes=None,
               provides=None,
               # most recent build_tools_version should be defined elsewhere
               build_tools_version="19.1.0",
               manifest='AndroidManifest.xml',
               release_type="debug",
               **kwargs):
    """
    :param string name: The name of this target, which combined with this
      build file defines the :doc:`target address <target_addresses>`.
    :param sources: Source code files to compile. Paths are relative to the
      BUILD file's directory.
    :type sources: ``Fileset`` or list of strings.
    :param excludes: List of :ref:`exclude <bdict_exclude>`\s
      to filter this target's transitive dependencies against.
    :param build_tools_version: API for the Build Tools (separate from SDK version).
      Defaults to the latest full release.
    :param manifest: path/to/file of 'AndroidManifest.xml' (required name). Paths are relative
      to the BUILD file's directory.
    :param release_type: Which keystore is used to sign target: 'debug' or 'release'.
      Set as 'debug' by default.
    """

    sources_rel_path = sources_rel_path or address.spec_path
    # No reasons why we might need AndroidPayload have presented themselves yet
    payload = JvmTargetPayload(sources=sources,
                               sources_rel_path=sources_rel_path,
                               provides=provides,
                               excludes=excludes)
    super(AndroidTarget, self).__init__(address=address, payload=payload, **kwargs)

    self.add_labels('android')
    self.build_tools_version = build_tools_version
    self.release_type = release_type

    self.manifest = os.path.join(self.address.spec_path, manifest)
    if not os.path.isfile(self.manifest):
      raise self.BadManifestError('Missing manifest at: {0!r}. Android targets require an '
                                  '\'AndroidManifest.xml\''.format(self.manifest))
    # TODO (mateor): varying manifest location means we should support variable manifest names

    self.package = self.get_package_name()
    self.target_sdk = self.get_target_sdk()

  # parsing as done in Donut testrunner
  def get_package_name(self):
    """Returns the package name of the Android target."""
    tgt_manifest = parse(self.manifest).getElementsByTagName('manifest')
    if not tgt_manifest or not tgt_manifest[0].getAttribute('package'):
      raise self.BadManifestError('There is no \'package\' attribute in manifest at: {0!r}'
                                  .format(self.manifest))
    return tgt_manifest[0].getAttribute('package')

  def get_target_sdk(self):
    """Returns a string with the Android package's target SDK."""
    tgt_manifest = parse(self.manifest).getElementsByTagName('uses-sdk')
    if not tgt_manifest or not tgt_manifest[0].getAttribute('android:targetSdkVersion'):
      raise self.BadManifestError('There is no \'targetSdkVersion\' attribute in manifest at: {0!r}'
                                  .format(self.manifest))
    return tgt_manifest[0].getAttribute('android:targetSdkVersion')
