# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from pants.backend.jvm.targets.jvm_target import JvmTarget


class ExportableJvmLibrary(JvmTarget):
  """A baseclass for java targets that support being exported to an artifact repository."""

  def __init__(self, *args, **kwargs):
    """
    :param string name: The name of this target, which combined with this
      build file defines the target :class:`pants.base.address.Address`.
    :param sources: A list of filenames representing the source code
      this library is compiled from.
    :type sources: list of strings
    :param provides:
      An optional Dependency object indicating the The ivy artifact to export.
    :param dependencies: List of :class:`pants.base.target.Target` instances
      this target depends on.
    :type dependencies: list of targets
    :param excludes: List of :class:`pants.targets.exclude.Exclude` instances
      to filter this target's transitive dependencies against.
    :param buildflags: Unused, and will be removed in a future release.
    """

    super(ExportableJvmLibrary, self).__init__(*args, **kwargs)

    self.add_labels('exportable')
