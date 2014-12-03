# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import os
from textwrap import dedent
import unittest2 as unittest

from pants.util.contextutil import temporary_dir

from square_backend.util.exclude_globally import Exclude, JarDependencyWithGlobalExcludes

class ExcludeGloballyTest(unittest.TestCase):
  old_global_excludes = []

  def setUp(self):
    self.old_global_excludes = JarDependencyWithGlobalExcludes.global_excludes
    JarDependencyWithGlobalExcludes.global_excludes=[]

  def tearDown(self):
    JarDependencyWithGlobalExcludes.global_excludes=self.old_global_excludes

  def testExclude(self):
    exclude = Exclude(org='foo', name='bar')
    self.assertEquals('foo', exclude.org)
    self.assertEquals('bar', exclude.name)

  def testExcludeGlobally(self):
    self.assertEquals([], JarDependencyWithGlobalExcludes.global_excludes)
    JarDependencyWithGlobalExcludes.exclude_globally('foo', 'bar')
    self.assertEquals(1, len(JarDependencyWithGlobalExcludes.global_excludes))
    self.assertEquals('foo', JarDependencyWithGlobalExcludes.global_excludes[0].org)
    self.assertEquals('bar', JarDependencyWithGlobalExcludes.global_excludes[0].name)

  def testLoadFromYaml(self):
    self.assertEquals([], JarDependencyWithGlobalExcludes.global_excludes)
    target = JarDependencyWithGlobalExcludes(org='foo', name='bar', rev='1.2.3')
    self.assertEquals(0, len(target.excludes))

    with temporary_dir() as yaml_dir:
      yaml_path = os.path.join(yaml_dir, "pants.yaml")
      with open(yaml_path, 'w') as yaml_file:
        yaml_file.write(dedent('''
        excludes:
          - org: com.google.protobuf
            name: protobuf-java
          - org: org.eclipse.jetty.orbit
            name: javax.servlet
        '''))
      JarDependencyWithGlobalExcludes.load_excludes_from_yaml(yaml_dir)
    loaded = JarDependencyWithGlobalExcludes.global_excludes
    self.assertEquals(2, len(loaded))
    self.assertEquals('com.google.protobuf', loaded[0].org)
    self.assertEquals('protobuf-java', loaded[0].name)
    self.assertEquals('org.eclipse.jetty.orbit', loaded[1].org)
    self.assertEquals('javax.servlet', loaded[1].name)

    target = JarDependencyWithGlobalExcludes(org='foo', name='bar', rev='1.2.3')
    self.assertEquals(2, len(target.excludes))
    self.assertEquals('com.google.protobuf', target.excludes[0].org)
    self.assertEquals('protobuf-java', target.excludes[0].name)
    self.assertEquals('org.eclipse.jetty.orbit', target.excludes[1].org)
    self.assertEquals('javax.servlet', target.excludes[1].name)



