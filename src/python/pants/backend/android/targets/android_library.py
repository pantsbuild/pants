# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pants.backend.android.android_manifest_parser import AndroidManifestParser
from pants.backend.android.targets.android_target import AndroidTarget
from pants.backend.jvm.targets.import_jars_mixin import ImportJarsMixin
from pants.base.payload import Payload
from pants.base.payload_field import PrimitiveField


class AndroidLibrary(ImportJarsMixin, AndroidTarget):
  """Android library projects that access Android API or Android resources.
  """
  def __init__(self, payload=None, libraries=None,
               include_patterns=None, exclude_patterns=None, **kwargs):
    """
    :param list libraries: List of addresses of `android_dependency <#android_dependency>`_
      targets.
    :param list include_patterns: fileset patterns to include from the archive
    :param list exclude_patterns: fileset patterns to exclude from the archive
    """

    # TODO(mateor) Perhaps add a BUILD file attribute to force archive type: one of (jar, aar).
    payload = payload or Payload()
    payload.add_fields({
      'library_specs': PrimitiveField(libraries or ())
    })
    self.libraries = libraries
    self.include_patterns = include_patterns or []
    self.exclude_patterns = exclude_patterns or []

    super(AndroidLibrary, self).__init__(payload=payload, **kwargs)

  @property
  def imported_jar_library_specs(self):
    """List of JarLibrary specs to import.

    Required to implement the ImportJarsMixin.
    """
    return self.payload.library_specs

  @property
  def manifest(self):
    """The manifest of the AndroidLibrary, if one exists."""
    # Libraries may not have a manifest, so allow that to be None for android_library targets.
    if self._manifest is None:
      if self._manifest_path is None:
        return None
      else:
        manifest = os.path.join(self._spec_path, self._manifest_path)
        self._manifest = AndroidManifestParser.parse_manifest(manifest)
    return self._manifest
