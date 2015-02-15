# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
from xml.dom.minidom import parse

from pants.backend.jvm.targets.jvm_target import JvmTarget
from pants.base.exceptions import TargetDefinitionException


class AndroidTarget(JvmTarget):
  """A base class for all Android targets."""

  # Missing attributes from the AndroidManifest would eventually error in the compilation process.
  # But since the error would raise here in the target definition, we are catching the exception.

  class BadManifestError(Exception):
    """Indicates an invalid android manifest."""

  def __init__(self,
               address=None,
               # TODO (mateor) add support for minSDk
               # most recent build_tools_version should be defined elsewhere
               build_tools_version="19.1.0",
               manifest=None,
               **kwargs):
    """
    :param build_tools_version: API for the Build Tools (separate from SDK version).
      Defaults to the latest full release.
    :param manifest: path/to/file of 'AndroidManifest.xml' (required name). Paths are relative
      to the BUILD file's directory.
    """
    super(AndroidTarget, self).__init__(address=address, **kwargs)
    self.add_labels('android')

    # TODO(pl): These attributes should live in the payload
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

  # TODO(mateor) Peel parsing into a ManifestParser class to ensure it's robust against bad input.
  # Parsing as in Android Donut's testrunner:
  # https://github.com/android/platform_development/blob/master/testrunner/android_manifest.py.
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
    try:
      package_name = tgt_manifest[0].getAttribute('android:name')
      return package_name.split(".")[-1]
    except:
      return None
