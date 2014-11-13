# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from pants.backend.jvm.targets.jvm_target import JvmTarget


class ScalaTests(JvmTarget):
  """Tests a Scala library with the Specs library. (You could use a `junit_test` instead.)"""

  def __init__(self, **kwargs):
    super(ScalaTests, self).__init__(**kwargs)
    self.add_labels('scala', 'tests')
