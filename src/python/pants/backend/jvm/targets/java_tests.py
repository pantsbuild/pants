# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.backend.jvm.targets.jvm_target import JvmTarget


class JavaTests(JvmTarget):
  """Tests JVM sources with JUnit."""

  def __init__(self, **kwargs):

    super(JavaTests, self).__init__(**kwargs)

    # TODO(John Sirois): These could be scala, clojure, etc.  'jvm' and 'tests' are the only truly
    # applicable labels - fixup the 'java' misnomer.
    self.add_labels('java', 'tests')
