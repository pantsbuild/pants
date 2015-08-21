# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import unittest

from pants.backend.jvm.jar_dependency_utils import M2Coordinate, ResolvedJar


class JarDependencyUtilsTest(unittest.TestCase):
  def test_m2_string_representation(self):
    org_name_ref = M2Coordinate(org='org.example', name='lib', rev='the-ref')
    self.assertEquals('org.example:lib:the-ref::jar', str(org_name_ref))

    org_name_ref_classifier = M2Coordinate(org='org.example', name='lib',
                                           rev='the-ref', classifier='classify')
    self.assertEquals('org.example:lib:the-ref:classify:jar', str(org_name_ref_classifier))

    org_name_classifier = M2Coordinate(org='org.example', name='lib',
                                           classifier='classify')
    self.assertEquals('org.example:lib::classify:jar', str(org_name_classifier))

    org_name_type_classifier = M2Coordinate(org='org.example', name='lib',
                            type_='zip',
                                       classifier='classify')
    self.assertEquals('org.example:lib::classify:zip', str(org_name_type_classifier))

    org_name_type_jar_classifier = M2Coordinate(org='org.example', name='lib',
                                            type_='jar',
                                            classifier='classify')
    self.assertEquals('org.example:lib::classify:jar', str(org_name_type_jar_classifier))

  def test_resolved_jars_with_differing_cache_paths_not_equal(self):
    jar1 = ResolvedJar(M2Coordinate('org.example', 'lib'), 'path1')
    jar2 = ResolvedJar(M2Coordinate('org.example', 'lib'), 'path2')

    self.assertNotEqual(jar1, jar2)


  def test_resolved_jars_with_differing_paths_not_equal(self):

    jar1 = ResolvedJar(M2Coordinate('org.example', 'lib'), 'ivy2/path', 'path1')
    jar2 = ResolvedJar(M2Coordinate('org.example', 'lib'), 'ivy2/path', 'path2')

    self.assertNotEqual(jar1, jar2)
