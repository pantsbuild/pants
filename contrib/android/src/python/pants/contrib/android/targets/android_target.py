# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pants.backend.jvm.targets.jvm_target import JvmTarget
from pants.base.exceptions import TargetDefinitionException
from pants.util.memo import memoized_property

from pants.contrib.android.android_manifest_parser import AndroidManifestParser


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

    self._manifest_file = manifest

  @memoized_property
  def manifest(self):
    """Return an AndroidManifest object made from a manifest by AndroidManifestParser."""

    # If there was no 'manifest' field in the BUILD file, try to find one with the default value.
    if self._manifest_file is None:
      self._manifest_file = 'AndroidManifest.xml'
    manifest_path = os.path.join(self._spec_path, self._manifest_file)
    if not os.path.isfile(manifest_path):
      raise TargetDefinitionException(self, "There is no AndroidManifest.xml at path {0}. Please "
                                            "declare a 'manifest' field with its relative "
                                            "path.".format(manifest_path))
    return AndroidManifestParser.parse_manifest(manifest_path)
