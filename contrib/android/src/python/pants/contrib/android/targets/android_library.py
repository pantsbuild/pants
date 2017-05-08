# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pants.backend.jvm.targets.import_jars_mixin import ImportJarsMixin
from pants.base.payload import Payload
from pants.base.payload_field import PrimitiveField
from pants.util.memo import memoized_property

from pants.contrib.android.android_manifest_parser import AndroidManifestParser
from pants.contrib.android.targets.android_target import AndroidTarget


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
      'library_specs': PrimitiveField(libraries or ()),
      'include_patterns' : PrimitiveField(include_patterns or ()),
      'exclude_patterns' : PrimitiveField(exclude_patterns or ()),
    })
    self.libraries = libraries


    super(AndroidLibrary, self).__init__(payload=payload, **kwargs)

  @classmethod
  def imported_jar_library_spec_fields(cls):
    """Yields fields to extract JarLibrary specs from.

    Required to implement the ImportJarsMixin.
    """
    yield ('libraries', 'library_specs')

  @memoized_property
  def manifest(self):
    """The manifest of the AndroidLibrary, if one exists."""
    # Libraries may not have a manifest, so self.manifest can be None for android_libraries.
    if self._manifest_file is None:
      return None
    else:
      manifest_path = os.path.join(self._spec_path, self._manifest_file)
    return AndroidManifestParser.parse_manifest(manifest_path)
