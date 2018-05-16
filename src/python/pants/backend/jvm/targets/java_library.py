# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.backend.jvm.targets.exportable_jvm_library import ExportableJvmLibrary
from pants.backend.jvm.targets.junit_tests import JUnitTests


class JavaLibrary(ExportableJvmLibrary):
  """A Java library.

  Normally has conceptually-related sources; invoking the ``compile`` goal
  on this target compiles Java and generates classes. Invoking the ``jar``
  goal on this target creates a ``.jar``; but that's an unusual thing to do.
  Instead, a ``jvm_binary`` might depend on this library; that binary is a
  more sensible thing to bundle.

  :API: public
  """

  default_sources_globs = '*.java'
  default_sources_exclude_globs = JUnitTests.java_test_globs

  @classmethod
  def subsystems(cls):
    return super(JavaLibrary, cls).subsystems()

  def __init__(self, address=None, **kwargs):
    super(JavaLibrary, self).__init__(address=address, **kwargs)
    if 'scalac_plugins' in kwargs:
      raise self.IllegalArgument(address.spec,
                                 'java_library does not support the scalac_plugins argument.')
    if 'scalac_plugin_args' in kwargs:
      raise self.IllegalArgument(address.spec,
                                 'java_library does not support the scalac_plugin_args argument.')
