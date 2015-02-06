# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import logging

import six

from pants.backend.jvm.targets.jar_library import JarLibrary
from pants.base.payload import Payload
from pants.base.payload_field import DeferredSourcesField, PrimitiveField
from pants.base.target import Target


logger = logging.getLogger(__name__)


class UnpackedJars(Target):
  """Describes a set of sources that are extracted from jar artifacts."""

  class ExpectedLibrariesError(Exception):
    """Thrown when the target has no libraries defined."""
    pass

  def __init__(self, payload=None, libraries=None, include_patterns=None, exclude_patterns=None,
               **kwargs):
    """
    :param libraries: List of addresses of `jar_library <#jar_library>`_
      targets which contain .proto definitions.
    :param list libraries: addresses of jar_library targets that specify the jars you want to unpack
    :param list include_patterns: fileset patterns to include from the archive
    :param list exclude_patterns: fileset patterns to exclude from the archive
    """
    payload = payload or Payload()
    payload.add_fields({
      'raw_libraries': PrimitiveField(libraries or ())
    })
    super(UnpackedJars, self).__init__(payload=payload, **kwargs)

    self.include_patterns = include_patterns or []
    self.exclude_patterns = exclude_patterns or []
    self._files = None

    if not libraries:
      raise  self.ExpectedLibrariesError('Expected non-empty libraries attribute for {spec}'
                                         .format(spec=self.address.spec))
    self._libraries = None

    # Make sure the ivy-imports task
    self.add_labels('has_imports')

  @property
  def traversable_specs(self):
    for spec in super(UnpackedJars, self).traversable_specs:
      yield spec
    if self.payload.raw_libraries:
      for spec  in self.payload.raw_libraries:
        if not isinstance(spec, six.string_types):
          raise JarLibrary.ExpectedAddressError(
            "{address}: expected imports to contain string addresses, got {found_class}."
            .format(address=self.address.spec,
                    found_class=type(spec).__name__))
        yield spec

  @property
  def imports(self):
    """Expected by the IvyImports tasks.

    :returns: the set of JarDependency instances to be included when compiling this target.
    """
    if self._libraries is None:
      self._libraries = JarLibrary.to_jar_dependencies(self.address,
                                                       self.payload.raw_libraries,
                                                       self._build_graph)
    return self._libraries
