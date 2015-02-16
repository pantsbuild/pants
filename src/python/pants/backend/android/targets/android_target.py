# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pants.backend.android.android_manifest_parser import AndroidManifestParser
from pants.backend.jvm.targets.jvm_target import JvmTarget
from pants.base.exceptions import TargetDefinitionException


class AndroidTarget(JvmTarget):
  """A base class for all Android targets."""


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
    self._spec_path = address.spec_path

    self._manifest = manifest
    self._manifest_path = None

    self._parsed = None
    self._package = None
    self._target_sdk = None
    self._app_name = None

  @property
  def manifest(self):
    """Return the relative path of the AndroidManifest.xml."""

    # For both gradle and ant layouts, AndroidManifest is conventionally at top-level.
    # As the file name is required by the tooling, I think providing that as a default is natural.
    # Still, I would recommend users explicitly define a 'manifest' in android BUILD files.
    if self._manifest_path is None:
      if self._manifest is None:
        self._manifest = 'AndroidManifest.xml'
      manifest = os.path.join(self._spec_path, self._manifest)
      if not os.path.isfile(manifest):
        raise TargetDefinitionException(self, "There is no AndroidManifest.xml at path {0}. Please "
                                              "declare a 'manifest' field with its relative "
                                              "path.".format(manifest))
      self._manifest_path = manifest
    return self._manifest_path

  @property
  def _parsed_manifest(self):
    """Parse AndroidManifest.xml.

    :returns AndroidManifestParser instance.
    """
    if self._parsed is None:
      try:
        self._parsed = AndroidManifestParser.from_file(self.manifest)
      except AndroidManifestParser.BadXmlException as e:
        raise TargetDefinitionException(self, 'Problem parsing the AndroidManifest.xml: '
                                              '{}'.format(e))
    return self._parsed

  @property
  def package_name(self):
    """Return the package name of the android_target, e.g. 'com.foo.bar'."""
    if self._package is None:
      self._package = AndroidManifestParser.get_package_name(self._parsed_manifest)
    return self._package

  @property
  def target_sdk(self):
    """Return the target sdk of the Android target."""
    if self._target_sdk is None:
      self._target_sdk = AndroidManifestParser.get_target_sdk(self._parsed_manifest)
    return self._target_sdk

  @property
  def app_name(self):
    """Retrieve the app name of the target or return None if it cannot be parsed."""
    # If unable to parse application name, silently falls back to target.name.
    if self._app_name is None:
      self._app_name = AndroidManifestParser.get_app_name(self._parsed_manifest) or self.name
    return self._app_name
