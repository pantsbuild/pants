# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

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
    :param string name: The name of this target, which combined with this
      build file defines the :doc:`target address <target_addresses>`.
    :param sources: Source code files to compile. Paths are relative to the
      BUILD file's directory.
    :type sources: ``Fileset`` or list of strings
    :param provides: The ``artifact``
      to publish that represents this target outside the repo.
    :param dependencies: Other targets that this target depends on. If your
       code ``import``\s code from other places, it depends on them.
    :type dependencies: list of target specs
    :param excludes: List of :ref:`exclude <bdict_exclude>`\s
      to filter this target's transitive dependencies against.
    :param resources: An optional list of file paths (DEPRECATED) or
      ``resources`` targets (which in turn point to file paths). The paths
      indicate text file resources to place in this module's jar.
    :param exclusives: An optional map of exclusives tags. See CheckExclusives for details.
    """
    super(JavaLibrary, self).__init__(*args, **kwargs)
    self.add_labels('java')
