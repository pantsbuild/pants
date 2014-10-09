# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)


from pants.backend.jvm.targets.jar_dependency import JarDependency
from pants.backend.jvm.targets.jar_library import JarLibrary

from pants_test.base_test import BaseTest


# TODO(Eric Ayers) there are a lot of tests to backfill
class JvmTargetTest(BaseTest):

  def setUp(self):
    super(JvmTargetTest, self).setUp()
    self.build_file_parser._build_configuration.register_target_alias('jar_library', JarLibrary)
    self.build_file_parser._build_configuration.register_exposed_object('jar', JarDependency)


