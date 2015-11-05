# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import unittest

from pants.backend.jvm.targets.exclude import Exclude
from pants.backend.jvm.targets.jar_dependency import JarDependency


class JarDependencyTest(unittest.TestCase):

  def test_jar_dependency_excludes_change_hash(self):
    exclude = Exclude(org='example.com', name='foo-lib')
    with_excludes = JarDependency(org='foo',
                                  name='foo',
                                  excludes=[exclude])
    without_excludes = JarDependency(org='foo', name='foo')
    self.assertNotEqual(with_excludes.cache_key(), without_excludes.cache_key())
