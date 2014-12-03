# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from textwrap import dedent

from pants.backend.jvm.targets.jar_dependency import JarDependency
from pants.backend.jvm.targets.jar_library import JarLibrary
from pants.backend.jvm.targets.jvm_target import JvmTarget
from pants.base.address import SyntheticAddress
from pants.base.build_file_aliases import BuildFileAliases

from pants_test.base_test import BaseTest


# TODO(Eric Ayers) there are a lot of tests to backfill
class JvmTargetTest(BaseTest):

  @property
  def alias_groups(self):
    return BuildFileAliases.create(targets={'jar_library': JarLibrary},
                                   objects={'jar': JarDependency})

  def test_to_jar_dependencies(self):
    def assert_dep(dep, org, name, rev):
      self.assertTrue(isinstance(dep, JarDependency))
      self.assertEquals(org, dep.org)
      self.assertEquals(name, dep.name)
      self.assertEquals(rev, dep.rev)

    self.add_to_build_file('BUILD', dedent('''
    jar_library(name='lib1',
      jars=[
        jar(org='testOrg1', name='testName1', rev='123'),
      ],
    )
    jar_library(name='lib2',
      jars=[
        jar(org='testOrg2', name='testName2', rev='456'),
        jar(org='testOrg3', name='testName3', rev='789'),
      ],
    )
    '''))
    lib1 = self.target('//:lib1')
    self.assertIsInstance(lib1, JarLibrary)
    self.assertEquals(1, len(lib1.jar_dependencies))
    assert_dep(lib1.jar_dependencies[0], 'testOrg1', 'testName1', '123')

    lib2 = self.target('//:lib2')
    self.assertIsInstance(lib2, JarLibrary)
    self.assertEquals(2, len(lib2.jar_dependencies))
    assert_dep(lib2.jar_dependencies[0], 'testOrg2', 'testName2', '456')
    assert_dep(lib2.jar_dependencies[1], 'testOrg3', 'testName3', '789')

    jvm_target = JvmTarget(name='dummy', address=SyntheticAddress.parse("//:dummy"),
                           build_graph=self.build_graph)
    deps = jvm_target.to_jar_dependencies([':lib1', ':lib2'])
    self.assertEquals(3, len(deps))
    assert_dep(lib1.jar_dependencies[0], 'testOrg1', 'testName1', '123')
    assert_dep(lib2.jar_dependencies[0], 'testOrg2', 'testName2', '456')
    assert_dep(lib2.jar_dependencies[1], 'testOrg3', 'testName3', '789')

