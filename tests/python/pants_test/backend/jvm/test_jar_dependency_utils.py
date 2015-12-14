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

    org_name_classifier = M2Coordinate(org='org.example', name='lib', classifier='classify')
    self.assertEquals('org.example:lib::classify:jar', str(org_name_classifier))

    org_name_type_classifier = M2Coordinate(org='org.example', name='lib',
                                            classifier='classify', ext='zip')
    self.assertEquals('org.example:lib::classify:zip', str(org_name_type_classifier))

    org_name_type_jar_classifier = M2Coordinate(org='org.example', name='lib',
                                                classifier='classify', ext='jar')
    self.assertEquals('org.example:lib::classify:jar', str(org_name_type_jar_classifier))

  def test_m2_coordinates_with_same_properties(self):
    coordinate1 = M2Coordinate('org.example', 'lib')
    coordinate2 = M2Coordinate('org.example', 'lib')

    self.assertEqual(coordinate1, coordinate2)
    self.assertEqual(hash(coordinate1), hash(coordinate2))

  def test_m2_coordinates_with_differing_properties_not_equal(self):
    coordinate1 = M2Coordinate('org.example', 'lib')
    coordinate2 = M2Coordinate('org.example', 'lib2')

    self.assertNotEqual(coordinate1, coordinate2)

  def test_m2_coordinates_with_different_types_have_different_hashes(self):
    coordinate1 = M2Coordinate('org.example', 'lib', ext='zip')
    coordinate2 = M2Coordinate('org.example', 'lib')

    self.assertNotEqual(hash(coordinate1), hash(coordinate2))

  def test_m2_coordinate_artifact_path_no_rev(self):
    coordinate = M2Coordinate('org.example', 'lib')

    self.assertEqual('org.example-lib.jar', coordinate.artifact_filename)

  def test_m2_coordinate_artifact_path_no_classifier(self):
    coordinate = M2Coordinate('org.example', 'lib', '1.0.0')

    self.assertEqual('org.example-lib-1.0.0.jar', coordinate.artifact_filename)

  def test_m2_coordinate_artifact_path_classifier(self):
    coordinate = M2Coordinate('org.example', 'lib', '1.0.0', 'sources')

    self.assertEqual('org.example-lib-1.0.0-sources.jar', coordinate.artifact_filename)

  def test_m2_coordinate_artifact_path_explicit_ext(self):
    coordinate = M2Coordinate('org.example', 'lib', '1.0.0', ext='tar.gz')

    self.assertEqual('org.example-lib-1.0.0.tar.gz', coordinate.artifact_filename)

  def test_resolved_jars_with_same_properties(self):
    jar1 = ResolvedJar(M2Coordinate('org.example', 'lib'), 'path')
    jar2 = ResolvedJar(M2Coordinate('org.example', 'lib'), 'path')

    self.assertEqual(jar1, jar2)
    self.assertEqual(hash(jar1), hash(jar2))

  def test_resolved_jars_with_differing_cache_paths_not_equal(self):
    jar1 = ResolvedJar(M2Coordinate('org.example', 'lib'), 'path1')
    jar2 = ResolvedJar(M2Coordinate('org.example', 'lib'), 'path2')

    self.assertNotEqual(jar1, jar2)

  def test_resolved_jars_with_differing_paths_not_equal(self):
    jar1 = ResolvedJar(M2Coordinate('org.example', 'lib'), 'ivy2/path', 'path1')
    jar2 = ResolvedJar(M2Coordinate('org.example', 'lib'), 'ivy2/path', 'path2')

    self.assertNotEqual(jar1, jar2)

  def test_resolved_jars_with_same_paths_equal(self):
    jar1 = ResolvedJar(M2Coordinate('org.example', 'lib'), 'ivy2/path', 'path')
    jar2 = ResolvedJar(M2Coordinate('org.example', 'lib'), 'ivy2/path', 'path')

    self.assertEqual(jar1, jar2)
