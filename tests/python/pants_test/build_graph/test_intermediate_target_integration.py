# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from hashlib import sha1

from pants_test.pants_run_integration_test import PantsRunIntegrationTest, ensure_engine


class BundleIntegrationTest(PantsRunIntegrationTest):

  def hash_target(self, address, scope):
    # This matches hashing in IntermediateTargetFactoryBase._create_intermediate_target.
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
    suffix = 'intransitive'

    hash_b = self.hash_target('{}:b'.format(test_path), suffix)
    hash_c = self.hash_target('{}:c'.format(test_path), suffix)

    self.assertEqual(
      {'testprojects/src/java/org/pantsbuild/testproject/intransitive:intransitive',
       'testprojects/src/java/org/pantsbuild/testproject/intransitive:diamond',
       'testprojects/src/java/org/pantsbuild/testproject/intransitive:b',
       'testprojects/src/java/org/pantsbuild/testproject/intransitive:c',
       'testprojects/src/java/org/pantsbuild/testproject/intransitive:b-unstable-{}-{}'.format(suffix, hash_b),
       'testprojects/src/java/org/pantsbuild/testproject/intransitive:c-unstable-{}-{}'.format(suffix, hash_c)},
      set(stdout_list))

  @ensure_engine
  def test_provided(self):
    test_path = 'testprojects/maven_layout/provided_patching'
    stdout_list = self.run_pants(['-q', 'list', '{}::'.format(test_path)]).stdout_data.strip().split()
    suffix = 'provided'

    hash_1 = self.hash_target('testprojects/maven_layout/provided_patching/one/src/main/java:shadow', suffix)
    hash_2 = self.hash_target('testprojects/maven_layout/provided_patching/two/src/main/java:shadow', suffix)
    hash_3 = self.hash_target('testprojects/maven_layout/provided_patching/three/src/main/java:shadow', suffix)

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
      'testprojects/maven_layout/provided_patching/one/src/main/java:shadow-unstable-{}-{}'.format(suffix, hash_1),
      'testprojects/maven_layout/provided_patching/two/src/main/java:shadow-unstable-{}-{}'.format(suffix, hash_2),
      'testprojects/maven_layout/provided_patching/three/src/main/java:shadow-unstable-{}-{}'.format(suffix, hash_3),
      'testprojects/maven_layout/provided_patching/leaf:shadow-unstable-{}-{}'.format(suffix, hash_2)
    }

    self.assertEqual(match_set, set(stdout_list))
