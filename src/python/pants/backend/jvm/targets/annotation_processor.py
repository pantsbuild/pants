# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.backend.jvm.targets.exportable_jvm_library import ExportableJvmLibrary


class AnnotationProcessor(ExportableJvmLibrary):
  """Produces a Java library containing one or more annotation processors."""

  def __init__(self, processors=None, *args, **kwargs):

    """
    :param resources: An optional list of file paths (DEPRECATED) or
      ``resources`` targets (which in turn point to file paths). The paths
      indicate text file resources to place in this module's jar.
    :param processors: A list of the fully qualified class names of the
      annotation processors this library exports.
    """
    super(AnnotationProcessor, self).__init__(*args, **kwargs)

    self.processors = processors

    # TODO(Eric Ayers) As of 2/5/2015 this call is DEPRECATED and should be removed soon
    self.add_labels('java', 'apt')
