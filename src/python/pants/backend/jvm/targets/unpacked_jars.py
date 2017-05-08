# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import logging

from pants.backend.jvm.targets.import_jars_mixin import ImportJarsMixin
from pants.base.payload import Payload
from pants.base.payload_field import PrimitiveField
from pants.build_graph.target import Target


logger = logging.getLogger(__name__)


class UnpackedJars(ImportJarsMixin, Target):
  """A set of sources extracted from JAR files.

  :API: public
  """

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
    :param list exclude_patterns: fileset patterns to exclude from the archive. Exclude patterns
      are processed before include_patterns.
    """
    payload = payload or Payload()
    payload.add_fields({
      'library_specs': PrimitiveField(libraries or ()),
      'include_patterns' : PrimitiveField(include_patterns or ()),
      'exclude_patterns' : PrimitiveField(exclude_patterns or ()),
    })
    super(UnpackedJars, self).__init__(payload=payload, **kwargs)

    self._files = None

    if not libraries:
      raise self.ExpectedLibrariesError('Expected non-empty libraries attribute for {spec}'
                                        .format(spec=self.address.spec))

  @classmethod
  def imported_jar_library_spec_fields(cls):
    """Fields to extract JarLibrary specs from.

    Required to implement the ImportJarsMixin.
    """
    yield ('libraries', 'library_specs')
