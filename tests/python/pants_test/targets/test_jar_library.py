# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)


from pants.backend.jvm.targets.jar_dependency import JarDependency
from pants.backend.jvm.targets.jar_library import JarLibrary
from pants.base.address import SyntheticAddress
from pants.base.exceptions import TargetDefinitionException
from pants.base.target import Target

from pants_test.base_test import BaseTest


class JarLibraryTest(BaseTest):

  def setUp(self):
    super(JarLibraryTest, self).setUp()
    self.build_file_parser._build_configuration.register_target_alias('jar_library', JarLibrary)
    self.build_file_parser._build_configuration.register_exposed_object('jar', JarDependency)

  def test_validation(self):
    target = Target(name='mybird', address=SyntheticAddress.parse('//:mybird'),
                    build_graph=self.build_graph)
    # jars attribute must contain only JarLibrary instances
    with self.assertRaises(TargetDefinitionException):
      JarLibrary(name="test", jars=[target])

  def test_jar_dependencies(self):
    jar1 = JarDependency(org='testOrg1', name='testName1', rev='123')
    jar2 = JarDependency(org='testOrg2', name='testName2', rev='456')
    lib = JarLibrary(name='foo', address=SyntheticAddress.parse('//:foo'),
                     build_graph=self.build_graph,
                     jars=[jar1, jar2])
    self.assertEquals((jar1, jar2), lib.jar_dependencies)

  def test_excludes(self):
    # TODO(Eric Ayers) There doesn't seem to be any way to set this field at the moment.
    lib = JarLibrary(name='foo', address=SyntheticAddress.parse('//:foo'),
                     build_graph=self.build_graph)
    self.assertEquals([], lib.excludes)
