# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from textwrap import dedent

#from pants.backend.jvm.targets.import_jars_mixin import ImportJarsMixin
from pants.backend.jvm.targets.jar_dependency import IvyArtifact, JarDependency
#from pants.base.address import BuildFileAddress
from pants_test.base_test import BaseTest


#from pants.backend.core.register import build_file_aliases as register_core
#from pants.backend.jvm.register import build_file_aliases as register_jvm
#from pants.backend.jvm.targets.unpacked_jars import UnpackedJars


class JarDependencyTest(BaseTest):

  #org, name, rev=None, force=False, ext=None, url=None, apidocs=None,
  #               type_=None, classifier=None, mutable=None, artifacts=None, intransitive=False

  # constructing JarDep w/ multiple artifacts and no classifier results in error on init
  # constructing w/ just an artifact in artifact list blows up nicely
  # artifact defaults name? Could do that to be less annoying.
  # add coordinate method that produces org,name,classifier
  # test jar dep w/ != classifiers are !=
  # test jar dep " " " " are not deduped in a set
  def test_jar_dependency_with_no_classifier_and_multiple_artifacts_fails_on_construction(self):
    def invalid_jar_dep():
      JarDependency('com.example',
                    'dependency',
                    artifacts=[IvyArtifact('dependency'), IvyArtifact('dependency2')])

    self.assertRaises(ValueError, invalid_jar_dep)

  def test_jar_dependency_with_single_artifact_with_no_list_fails(self):
    def invalid_jar_dep():
      JarDependency('com.example',
                    'dependency',
                    artifacts=IvyArtifact('dependency'))

    self.assertRaises(ValueError, invalid_jar_dep)

  def test_jars_with_different_classifiers_are_not_equal(self):
    jar_dep_c1 = JarDependency('com.example', 'dependency', classifier='c1')
    jar_dep_c2 = JarDependency('com.example', 'dependency', classifier='c2')

    self.assertNotEqual(jar_dep_c1, jar_dep_c2)

  def test_jars_with_no_classifiers_are_equal(self):
    jar_dep_1 = JarDependency('com.example', 'dependency')
    jar_dep_2 = JarDependency('com.example', 'dependency')

    self.assertEqual(jar_dep_1, jar_dep_2)

  def test_jars_with_different_classifiers_dont_hash_to_the_same_value(self):
    jar_dep_c1 = JarDependency('com.example', 'dependency', classifier='c1')
    jar_dep_c2 = JarDependency('com.example', 'dependency', classifier='c2')

    self.assertEqual(2, len({jar_dep_c1, jar_dep_c2}))

  def test_a_jar_with_rev_less_than_other_jar_is_less_than(self):
    jar_dep_1_0 = JarDependency('com.example', 'dependency', rev="1.0")
    jar_dep_1_1 = JarDependency('com.example', 'dependency', rev="1.1")

    self.assertTrue(jar_dep_1_0 < jar_dep_1_1,
                    '{} should be less than {}'.format(jar_dep_1_0, jar_dep_1_1))

  def test_a_jar_with_classifier_and_artifact_with_classifier_has_kwarg_as_classifier(self):
    jar_dep = JarDependency('com.example', 'dependency',
                            classifier='direct',
                            artifacts=[IvyArtifact('dep', classifier="artifact")])

    self.assertEqual('direct', jar_dep.classifier)

