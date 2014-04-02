# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import os
import shutil
import tempfile
import unittest

from twitter.common.collections import OrderedSet
from twitter.common.dirutil import safe_mkdir, touch

from pants.base.build_file import BuildFile


class BuildFileTest(unittest.TestCase):

  @classmethod
  def makedirs(cls, path):
    safe_mkdir(os.path.join(BuildFileTest.root_dir, path))

  @classmethod
  def touch(cls, path):
    touch(os.path.join(BuildFileTest.root_dir, path))

  @classmethod
  def buildfile(cls, path):
    return BuildFile(BuildFileTest.root_dir, path)

  @classmethod
  def setUpClass(cls):
    BuildFileTest.base_dir = tempfile.mkdtemp()

    # Seed a BUILD outside the build root that should not be detected
    touch(os.path.join(BuildFileTest.base_dir, 'BUILD'))

    BuildFileTest.root_dir = os.path.join(BuildFileTest.base_dir, 'root')

    BuildFileTest.touch('grandparent/parent/BUILD')
    BuildFileTest.touch('grandparent/parent/BUILD.twitter')
    BuildFileTest.makedirs('grandparent/parent/BUILD.dir')
    BuildFileTest.makedirs('grandparent/BUILD')
    BuildFileTest.touch('BUILD')
    BuildFileTest.touch('BUILD.twitter')
    BuildFileTest.touch('grandparent/parent/child1/BUILD')
    BuildFileTest.touch('grandparent/parent/child1/BUILD.twitter')
    BuildFileTest.touch('grandparent/parent/child2/child3/BUILD')
    BuildFileTest.makedirs('grandparent/parent/child2/BUILD')
    BuildFileTest.makedirs('grandparent/parent/child4')

  @classmethod
  def tearDownClass(cls):
    shutil.rmtree(BuildFileTest.root_dir)

  def setUp(self):
    self.buildfile = BuildFileTest.buildfile('grandparent/parent/BUILD')

  def testSiblings(self):
    buildfile = BuildFileTest.buildfile('grandparent/parent/BUILD.twitter')
    self.assertEquals(OrderedSet([buildfile]), OrderedSet(self.buildfile.siblings()))
    self.assertEquals(OrderedSet([self.buildfile]), OrderedSet(buildfile.siblings()))

    buildfile = BuildFileTest.buildfile('grandparent/parent/child2/child3/BUILD')
    self.assertEquals(OrderedSet(), OrderedSet(buildfile.siblings()))

  def testFamily(self):
    self.assertEquals(OrderedSet([
        BuildFileTest.buildfile('grandparent/parent/BUILD'),
        BuildFileTest.buildfile('grandparent/parent/BUILD.twitter'),
    ]), self.buildfile.family())

    buildfile = BuildFileTest.buildfile('grandparent/parent/child2/child3/BUILD')
    self.assertEquals(OrderedSet([buildfile]), buildfile.family())

  def testAncestors(self):
    self.assertEquals(OrderedSet([
        BuildFileTest.buildfile('BUILD'),
        BuildFileTest.buildfile('BUILD.twitter'),
    ]), self.buildfile.ancestors())

  def testDescendants(self):
    self.assertEquals(OrderedSet([
        BuildFileTest.buildfile('grandparent/parent/child1/BUILD'),
        BuildFileTest.buildfile('grandparent/parent/child1/BUILD.twitter'),
        BuildFileTest.buildfile('grandparent/parent/child2/child3/BUILD'),
    ]), self.buildfile.descendants())
