# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from hashlib import sha1

from pants_test.pants_run_integration_test import PantsRunIntegrationTest, ensure_engine


class BundleIntegrationTest(PantsRunIntegrationTest):

  def hash_target(self, address, scope):
    hasher = sha1()
    hasher.update(address)
    hasher.update(scope)
    return hasher.hexdigest()

  @ensure_engine
  def test_scoped(self):
    test_path = 'testprojects/src/java/org/pantsbuild/testproject/runtime'
    scoped_address = '3rdparty:gson'
    stdout_list = self.run_pants(['-q', 'list', '{}:'.format(test_path)]).stdout_data.strip().split()

    hash_1 = self.hash_target(scoped_address, 'compile')
    hash_2 = self.hash_target(scoped_address, 'runtime')
    self.assertEqual(
      {'testprojects/src/java/org/pantsbuild/testproject/runtime:compile-fail',
       'testprojects/src/java/org/pantsbuild/testproject/runtime:runtime-fail',
       'testprojects/src/java/org/pantsbuild/testproject/runtime:runtime-pass',
       'testprojects/src/java/org/pantsbuild/testproject/runtime:compile-pass',
       'testprojects/src/java/org/pantsbuild/testproject/runtime:gson-unstable-compile-{}'.format(hash_1),
       'testprojects/src/java/org/pantsbuild/testproject/runtime:gson-unstable-runtime-{}'.format(hash_2)},
      set(stdout_list))

  @ensure_engine
  def test_intransitive(self):
    test_path = 'testprojects/src/java/org/pantsbuild/testproject/intransitive'
    stdout_list = self.run_pants(['-q', 'list', '{}:'.format(test_path)]).stdout_data.strip().split()
    scope = 'intransitive'

    scoped_address = '{}:b'.format(test_path)
    hash_b = self.hash_target(scoped_address, scope)
    scoped_address = '{}:c'.format(test_path)
    hash_c = self.hash_target(scoped_address, scope)

    self.assertEqual(
      {'testprojects/src/java/org/pantsbuild/testproject/intransitive:intransitive',
       'testprojects/src/java/org/pantsbuild/testproject/intransitive:diamond',
       'testprojects/src/java/org/pantsbuild/testproject/intransitive:b',
       'testprojects/src/java/org/pantsbuild/testproject/intransitive:c',
       'testprojects/src/java/org/pantsbuild/testproject/intransitive:b-unstable-intransitive-{}'.format(hash_b),
       'testprojects/src/java/org/pantsbuild/testproject/intransitive:c-unstable-intransitive-{}'.format(hash_c)},
      set(stdout_list))

  @ensure_engine
  def test_provided(self):
    test_path = 'testprojects/maven_layout/provided_patching'
    stdout_list = self.run_pants(['-q', 'list', '{}::'.format(test_path)]).stdout_data.strip().split()
    scope = 'intransitive'

    scoped_address = 'testprojects/maven_layout/provided_patching/one/src/main/java:shadow'
    hash_1 = self.hash_target(scoped_address, scope)
    scoped_address = 'testprojects/maven_layout/provided_patching/two/src/main/java:shadow'
    hash_2 = self.hash_target(scoped_address, scope)
    scoped_address = 'testprojects/maven_layout/provided_patching/three/src/main/java:shadow'
    hash_3 = self.hash_target(scoped_address, scope)

    match_set = {
      'testprojects/maven_layout/provided_patching/one/src/main/java:common',
      'testprojects/maven_layout/provided_patching/one/src/main/java:shadow',
      'testprojects/maven_layout/provided_patching/two/src/main/java:shadow',
      'testprojects/maven_layout/provided_patching/two/src/main/java:common',
      'testprojects/maven_layout/provided_patching/three/src/main/java:common',
      'testprojects/maven_layout/provided_patching/three/src/main/java:shadow',
      'testprojects/maven_layout/provided_patching/leaf:test',
      'testprojects/maven_layout/provided_patching/leaf:fail',
      'testprojects/maven_layout/provided_patching/leaf:one',
      'testprojects/maven_layout/provided_patching/leaf:three',
      'testprojects/maven_layout/provided_patching/leaf:two',
      'testprojects/maven_layout/provided_patching/one/src/main/java:shadow-unstable-intransitive-{}'.format(hash_1),
      'testprojects/maven_layout/provided_patching/three/src/main/java:shadow-unstable-intransitive-{}'.format(hash_3),
    }

    # The below is because in v2 engine, the execution order is undetermined.
    # If 2 targets with different spec_path have same "provided" field,
    # then the intermediate target can be created under either spec paths.
    try:
      self.assertEqual(
        match_set.union(
          {'testprojects/maven_layout/provided_patching/leaf:shadow-unstable-intransitive-{}'.format(hash_2)}),
        set(stdout_list)
      )
    except AssertionError:
      self.assertEqual(
        match_set.union(
          {'testprojects/maven_layout/provided_patching/two/src/main/java:shadow-unstable-intransitive-{}'.format(hash_2)}),
        set(stdout_list)
      )
