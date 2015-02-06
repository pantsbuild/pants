# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.backend.jvm.targets.jvm_target import JvmTarget


class ExportableJvmLibrary(JvmTarget):
  """A baseclass for java targets that support being exported to an artifact repository."""

  def __init__(self, *args, **kwargs):
    """
    :param provides:
      An optional Dependency object indicating the The ivy artifact to export.
    """

    super(ExportableJvmLibrary, self).__init__(*args, **kwargs)

    self.add_labels('exportable')
