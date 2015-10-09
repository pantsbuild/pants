# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from textwrap import dedent

from pants.backend.jvm.targets.jar_dependency import JarDependency
from pants.backend.jvm.targets.jar_library import JarLibrary
from pants.base.exceptions import TargetDefinitionException
from pants.build_graph.address import Address
from pants.build_graph.build_file_aliases import BuildFileAliases
from pants.build_graph.target import Target
from pants_test.base_test import BaseTest


jar1 = JarDependency(org='testOrg1', name='testName1', rev='123')
jar2 = JarDependency(org='testOrg2', name='testName2', rev='456')


class JarLibraryTest(BaseTest):

  @property
  def alias_groups(self):
    return BuildFileAliases(targets={'jar_library': JarLibrary},
                            objects={'jar': JarDependency})

  def test_validation(self):
    target = Target(name='mybird', address=Address.parse('//:mybird'),
                    build_graph=self.build_graph)
    # jars attribute must contain only JarLibrary instances
    with self.assertRaises(TargetDefinitionException):
      JarLibrary(name="test", jars=[target])

  def test_jar_dependencies(self):
    lib = JarLibrary(name='foo', address=Address.parse('//:foo'),
                     build_graph=self.build_graph,
                     jars=[jar1, jar2])
    self.assertEquals((jar1, jar2), lib.jar_dependencies)

  def test_empty_jar_dependencies(self):
    def example():
      return self.make_target('//:foo', JarLibrary)
    self.assertRaises(TargetDefinitionException, example)

  def test_excludes(self):
    # TODO(Eric Ayers) There doesn't seem to be any way to set this field at the moment.
    lib = JarLibrary(name='foo', address=Address.parse('//:foo'),
                     build_graph=self.build_graph, jars=[jar1])
    self.assertEquals([], lib.excludes)

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

    deps = JarLibrary.to_jar_dependencies(lib1.address,
                                          [':lib1', ':lib2'],
                                          self.build_graph)
    self.assertEquals(3, len(deps))
    assert_dep(lib1.jar_dependencies[0], 'testOrg1', 'testName1', '123')
    assert_dep(lib2.jar_dependencies[0], 'testOrg2', 'testName2', '456')
    assert_dep(lib2.jar_dependencies[1], 'testOrg3', 'testName3', '789')
