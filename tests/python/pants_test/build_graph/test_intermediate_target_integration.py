# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.build_graph.intermediate_target_factory import hash_target
from pants_test.pants_run_integration_test import PantsRunIntegrationTest, ensure_engine


class IntermediateTargetIntegrationTest(PantsRunIntegrationTest):

  @ensure_engine
  def test_scoped(self):
    test_path = 'testprojects/src/java/org/pantsbuild/testproject/runtime'
    scoped_address = '3rdparty:gson'
    stdout_list = self.run_pants(['-q', 'list', '{}:'.format(test_path)]).stdout_data.strip().split()

    hash_1 = hash_target(scoped_address, 'compile')
    hash_2 = hash_target(scoped_address, 'runtime')
    self.assertIn(
      'testprojects/src/java/org/pantsbuild/testproject/runtime:gson-unstable-compile-{}'.format(hash_1),
      stdout_list
    )

    self.assertIn(
      'testprojects/src/java/org/pantsbuild/testproject/runtime:gson-unstable-runtime-{}'.format(hash_2),
      stdout_list
    )

  @ensure_engine
  def test_intransitive(self):
    test_path = 'testprojects/src/java/org/pantsbuild/testproject/intransitive'
    stdout_list = self.run_pants(['-q', 'list', '{}:'.format(test_path)]).stdout_data.strip().split()
    suffix = 'intransitive'

    hash_b = hash_target('{}:b'.format(test_path), suffix)
    hash_c = hash_target('{}:c'.format(test_path), suffix)

    self.assertIn(
      'testprojects/src/java/org/pantsbuild/testproject/intransitive:b-unstable-{}-{}'.format(suffix, hash_b),
      stdout_list
    )

    self.assertIn(
      'testprojects/src/java/org/pantsbuild/testproject/intransitive:c-unstable-{}-{}'.format(suffix, hash_c),
      stdout_list
    )

  @ensure_engine
  def test_provided(self):
    test_path = 'testprojects/maven_layout/provided_patching'
    stdout_list = self.run_pants(['-q', 'list', '{}::'.format(test_path)]).stdout_data.strip().split()
    suffix = 'provided'

    hash_1 = hash_target('testprojects/maven_layout/provided_patching/one/src/main/java:shadow', suffix)
    hash_2 = hash_target('testprojects/maven_layout/provided_patching/two/src/main/java:shadow', suffix)
    hash_3 = hash_target('testprojects/maven_layout/provided_patching/three/src/main/java:shadow', suffix)

    self.assertIn(
      'testprojects/maven_layout/provided_patching/one/src/main/java:shadow-unstable-{}-{}'.format(suffix, hash_1),
      stdout_list
    )

    self.assertIn(
      'testprojects/maven_layout/provided_patching/two/src/main/java:shadow-unstable-{}-{}'.format(suffix, hash_2),
      stdout_list
    )

    self.assertIn(
      'testprojects/maven_layout/provided_patching/three/src/main/java:shadow-unstable-{}-{}'.format(suffix, hash_3),
      stdout_list
    )

    self.assertIn(
      'testprojects/maven_layout/provided_patching/leaf:shadow-unstable-{}-{}'.format(suffix, hash_2),
      stdout_list
    )

  @ensure_engine
  def test_no_redundant_target(self):
    # TODO: Create another BUILD.other file with same provided scope,
    # once we resolve https://github.com/pantsbuild/pants/issues/3933
    test_path = 'testprojects/maven_layout/provided_patching/one/src/main/java'
    stdout_list = self.run_pants(['-q', 'list', '{}::'.format(test_path)]).stdout_data.strip().split()
    suffix = 'provided'

    hash = hash_target('{}:shadow'.format(test_path), suffix)
    synthetic_target = '{}:shadow-unstable-{}-{}'.format(test_path, suffix, hash)
    self.assertEqual(
      stdout_list.count(synthetic_target),
      1
    )
