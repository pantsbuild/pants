# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.backend.jvm.targets.jar_dependency import IvyArtifact, JarDependency
from pants.backend.jvm.targets.jar_library import JarLibrary
from pants.backend.jvm.targets.scala_library import ScalaLibrary
from pants.backend.jvm.tasks.ivy_resolve import IvyResolve
from pants_test.jvm.jvm_tool_task_test_base import JvmToolTaskTestBase


class IvyResolveTest(JvmToolTaskTestBase):
  """Tests for the class IvyResolve."""

  @classmethod
  def task_type(cls):
    return IvyResolve

  def setUp(self):
    super(IvyResolveTest, self).setUp()
    self.set_options(
        read_artifact_caches=None,
        write_artifact_caches=None,
        use_nailgun=False)

  def resolve(self, targets):
    """Given some targets, execute a resolve, and return the resulting compile_classpath."""
    context = self.context(target_roots=targets)
    self.create_task(context, 'unused').execute()
    return context.products.get_data('compile_classpath', None)

  #
  # Test section
  #

  def test_resolve_specific(self):
    # Create a jar_library with a single dep, and another library with no deps.
    dep = JarDependency('commons-lang', 'commons-lang', '2.5')
    jar_lib = self.make_target('//:a', JarLibrary, jars=[dep])
    scala_lib = self.make_target('//:b', ScalaLibrary)
    # Confirm that the deps were added to the appropriate targets.
    compile_classpath = self.resolve([jar_lib, scala_lib])
    self.assertEquals(1, len(compile_classpath.get_for_target(jar_lib)))
    self.assertEquals(0, len(compile_classpath.get_for_target(scala_lib)))

  def test_resolve_conflicted(self):
    # Create jar_libraries with different versions of the same dep: this will cause
    # a pre-ivy "eviction" in IvyUtils.generate_ivy, but the same case can be triggered
    # due to an ivy eviction where the declared version loses to a transitive version.
    losing_dep = JarDependency('com.google.guava', 'guava', '16.0')
    winning_dep = JarDependency('com.google.guava', 'guava', '16.0.1')
    losing_lib = self.make_target('//:a', JarLibrary, jars=[losing_dep])
    winning_lib = self.make_target('//:b', JarLibrary, jars=[winning_dep])
    # Confirm that the same artifact was added to each target.
    compile_classpath = self.resolve([losing_lib, winning_lib])
    losing_cp = compile_classpath.get_for_target(losing_lib)
    winning_cp = compile_classpath.get_for_target(winning_lib)
    self.assertEquals(losing_cp, winning_cp)
    self.assertEquals(1, len(winning_cp))

  def test_resolve_multiple_artifacts(self):
    no_classifier = JarDependency('junit', 'junit', rev='4.12')
    classifier_and_no_classifier = JarDependency('junit', 'junit', rev='4.12', classifier='sources', artifacts=[IvyArtifact('junit')])

    no_classifier_lib = self.make_target('//:a', JarLibrary, jars=[no_classifier])
    classifier_and_no_classifier_lib = self.make_target('//:b', JarLibrary, jars=[classifier_and_no_classifier])

    compile_classpath = self.resolve([no_classifier_lib, classifier_and_no_classifier_lib])

    no_classifier_cp = compile_classpath.get_for_target(no_classifier_lib)
    classifier_and_no_classifier_cp = compile_classpath.get_for_target(classifier_and_no_classifier_lib)

    sources_jar = 'junit-4.12-sources.jar'
    regular_jar = 'junit-4.12.jar'
    self.assertTrue(any(sources_jar in j[-1] for j in classifier_and_no_classifier_cp), 'expected {} in {}'.format(sources_jar, classifier_and_no_classifier_cp))
    self.assertTrue(any(regular_jar in j[-1] for j in classifier_and_no_classifier_cp), 'expected {} in {}'.format(regular_jar, classifier_and_no_classifier_cp))

    self.assertTrue(all(sources_jar not in j[-1] for j in no_classifier_cp), 'expected {} to not be in {}'.format(regular_jar, no_classifier_cp))
    self.assertTrue(any(regular_jar in j[-1] for j in no_classifier_cp), 'expected {} in {}'.format(regular_jar, no_classifier_cp))

  def test_resolve_no_deps(self):
    # Resolve a library with no deps, and confirm that the empty product is created.
    target = self.make_target('//:a', ScalaLibrary)
    self.assertTrue(self.resolve([target]))
