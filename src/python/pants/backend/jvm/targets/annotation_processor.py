# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from pants.backend.jvm.targets.exportable_jvm_library import ExportableJvmLibrary


class AnnotationProcessor(ExportableJvmLibrary):
  """Produces a Java library containing one or more annotation processors."""

  def __init__(self, processors=None, *args, **kwargs):

    """
    :param string name: The name of this target, which combined with this
      build file defines the :doc:`target address <target_addresses>`.
    :param sources: Source code files to compile. Paths are relative to the
      BUILD file's directory.
    :type sources: ``Fileset`` or list of strings
    :param provides: The ``artifact``
      to publish that represents this target outside the repo.
    :param dependencies: Other targets that this target depends on.
    :type dependencies: list of target specs
    :param excludes: List of :ref:`exclude <bdict_exclude>`\s
      to filter this target's transitive dependencies against.
    :param resources: An optional list of file paths (DEPRECATED) or
      ``resources`` targets (which in turn point to file paths). The paths
      indicate text file resources to place in this module's jar.
    :param processors: A list of the fully qualified class names of the
      annotation processors this library exports.
    :param exclusives: An optional map of exclusives tags. See CheckExclusives for details.
    """
    super(AnnotationProcessor, self).__init__(*args, **kwargs)

    self.processors = processors
    self.add_labels('java', 'apt')
