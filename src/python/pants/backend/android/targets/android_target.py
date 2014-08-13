# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE)

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import os
from xml.dom.minidom import parse

from pants.backend.jvm.targets.jvm_target import JvmTarget
from pants.base.exceptions import TargetDefinitionException


class AndroidTarget(JvmTarget):
  """A base class for all Android targets."""

  # Missing attributes from the AndroidManifest would eventually error in the compilation process.
  # But since the error would raise here in the target definition, we are catching the exception
  class BadManifestError(Exception):
    """Indicates an invalid android manifest."""

  def __init__(self,
               address=None,
               # TODO (mateor) add support for minSDk
               build_type = None,
               # most recent build_tools_version should be defined elsewhere
               build_tools_version="19.1.0",
               manifest=None,
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
    super(AndroidTarget, self).__init__(address=address, **kwargs)

    # TODO(mateor) support for 'release' builds
    self.build_type = 'debug'
    if self.build_type is not 'debug':
      if self.build_type is not 'release':
        raise TargetDefinitionException(self, 'Pants currently only supports debug build type.')
    self.add_labels('android')
    self.build_tools_version = build_tools_version

    if manifest is None:
      raise TargetDefinitionException(self, 'Android targets require a manifest attribute.')
    manifest_path = os.path.join(address.spec_path, manifest)
    if not os.path.isfile(manifest_path):
      raise TargetDefinitionException(self, 'The given manifest {0} is not a file '
                                            'at path {1}'.format(manifest, manifest_path))
    self.manifest = manifest_path

    self.package = self.get_package_name()
    self.target_sdk = self.get_target_sdk()
    # If unable to parse application name, silently falls back to target name.
    self.app_name = self.get_app_name() if self.get_app_name() else self.name

  # TODO(mateor) Peel parsing into a ManifestParser class, to ensure it's robust against bad input
  # Parsing as in Android Donut's testrunner:
  # https://github.com/android/platform_development/blob/master/testrunner/android_manifest.py
  def get_package_name(self):
    """Return the package name of the Android target."""
    tgt_manifest = parse(self.manifest).getElementsByTagName('manifest')
    if not tgt_manifest or not tgt_manifest[0].getAttribute('package'):
      raise self.BadManifestError('There is no \'package\' attribute in manifest at: {0!r}'
                                  .format(self.manifest))
    return tgt_manifest[0].getAttribute('package')

  def get_target_sdk(self):
    """Return a string with the Android package's target SDK."""
    tgt_manifest = parse(self.manifest).getElementsByTagName('uses-sdk')
    if not tgt_manifest or not tgt_manifest[0].getAttribute('android:targetSdkVersion'):
      raise self.BadManifestError('There is no \'targetSdkVersion\' attribute in manifest at: {0!r}'
                                  .format(self.manifest))
    return tgt_manifest[0].getAttribute('android:targetSdkVersion')

  def get_app_name(self):
    """Return a string with the application name of the package, return None if not found."""
    tgt_manifest = parse(self.manifest).getElementsByTagName('activity')
    package_name = tgt_manifest[0].getAttribute('android:name')
    return package_name.split(".")[-1]

  def is_android(self):
    return True
