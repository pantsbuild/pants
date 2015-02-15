# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.backend.jvm.targets.exportable_jvm_library import ExportableJvmLibrary


class JavaLibrary(ExportableJvmLibrary):
  """A collection of Java code.

  Normally has conceptually-related sources; invoking the ``compile`` goal
  on this target compiles Java and generates classes. Invoking the ``jar``
  goal on this target creates a ``.jar``; but that's an unusual thing to do.
  Instead, a ``jvm_binary`` might depend on this library; that binary is a
  more sensible thing to bundle.
  """

  def __init__(self, *args, **kwargs):
    """
    :param provides: The ``artifact``
      to publish that represents this target outside the repo.
    :param resources: An optional list of file paths (DEPRECATED) or
      ``resources`` targets (which in turn point to file paths). The paths
      indicate text file resources to place in this module's jar.
    """
    super(JavaLibrary, self).__init__(*args, **kwargs)
    self.add_labels('java')
