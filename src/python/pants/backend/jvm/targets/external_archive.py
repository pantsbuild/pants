# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import logging
import six

from pants.backend.core.targets.source_set import SourceSet
from pants.backend.jvm.targets.jar_library import JarLibrary
from pants.base.payload import Payload
from pants.base.payload_field import PrimitiveField

logger = logging.getLogger(__name__)

class ExternalArchive(SourceSet):
  """A target that allows importing an artifact from an external repository."""

  class ExpectedImportsError(Exception):
    """Thrown when the target is defined with no imports defined."""
    pass

  class SourceSetNotPopulatedError(Exception):
     """Thrown if a call to extract the files is made before the source set is populated.

     This indicates a bug in pants, not a problem with a BUILD file definition
     """
     pass

  def __init__(self, payload=None, imports=None, include_patterns=None, exclude_patterns=None,
      unpack=True,  **kwargs):
    """
    :param imports: List of addresses of `jar_library <#jar_library>`_
      targets which contain .proto definitions.
    :param list include_patterns: fileset patterns to include from the archive
    :param list exclude_patterns: fileset patterns to exclude from the archive
    :param boolean unpack: if True, decompresses the archive and extracts it using
      includes and excludes.
    """
    payload = payload or Payload()
    payload.add_fields({
      'raw_imports': PrimitiveField(imports or ())
    })
    super(ExternalArchive, self).__init__(payload=payload, **kwargs)

    self.include_patterns = include_patterns or []
    self.exclude_patterns = exclude_patterns or []
    self.unpack = unpack
    self._files = None

    if not imports:
      raise  self.ExpectedImportsError('Expected non-empty imports attribute for {spec}'
                                  .format(spec=self.address.spec))
    self._imports = None

    self.add_labels('has_imports')

    if (include_patterns or exclude_patterns) and not unpack:
      logger.warn('Target {spec} has unpacking disabled.  "'
                  '"includes and excludes attributes will be ignored.'
                  .format(spec=self.address.spec))

  @property
  def traversable_specs(self):
    for spec in super(ExternalArchive, self).traversable_specs:
      yield spec
    if self.payload.raw_imports:
      for spec  in self.payload.raw_imports:
        # This simply skips over non-strings, but we catch them with a WrongTargetType below.
        if isinstance(spec, six.string_types):
          yield spec

  @property
  def imports(self):
    """Returns the set of JarDependency instances to be included when compiling this target."""
    if self._imports is None:
      self._imports = JarLibrary.to_jar_dependencies(self.address,
                                                     self.payload.raw_imports,
                                                     self._build_graph)
    return self._imports

  def populate(self, files, rel_path=None, source_root=None):
    """Call this method to set the list of files represented by the SourceSet.
    Intended to be invoked by the UnpackExternalArchive task.
    :param list files: strings representing absolute paths of files to be included in the source set
    :param string rel_path: common prefix for files.
    :param string source_root: root of the source paths for compiling these files.
    """
    self._files = files
    self._rel_path = rel_path
    self._source_root = source_root

  def files(self):
    if self._files is None:
      raise self.SourceSetNotPopulatedError("SourceSet imported from( {spec} ) has not been populated."
                                            .format(spec=self.address.spec))
    return self._files
