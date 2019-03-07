# coding=utf-8
# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import os
import re
from builtins import str
from contextlib import contextmanager

from future.utils import PY3
from mock import MagicMock
from psutil.tests import safe_rmpath

from pants.backend.jvm.subsystems.jar_dependency_management import (JarDependencyManagement,
                                                                    PinnedJarArtifactSet)
from pants.backend.jvm.targets.jar_library import JarLibrary
from pants.backend.jvm.targets.java_library import JavaLibrary
from pants.backend.jvm.targets.jvm_target import JvmTarget
from pants.backend.jvm.targets.managed_jar_dependencies import ManagedJarDependencies
from pants.backend.jvm.tasks.classpath_products import ClasspathProducts
from pants.backend.jvm.tasks.coursier_resolve import (CoursierResolve,
                                                      CoursierResolveFingerprintStrategy)
from pants.backend.jvm.tasks.nailgun_task import NailgunTask
from pants.base.exceptions import TaskError
from pants.java import util
from pants.java.jar.exclude import Exclude
from pants.java.jar.jar_dependency import JarDependency
from pants.task.task import Task
from pants.util.contextutil import temporary_dir, temporary_file_path
from pants.util.dirutil import safe_rmtree
from pants_test.jvm.jvm_tool_task_test_base import JvmToolTaskTestBase
from pants_test.subsystem.subsystem_util import init_subsystem
from pants_test.task_test_base import TaskTestBase


class CoursierResolveTest(JvmToolTaskTestBase):
  """Tests for the class CoursierResolve."""

  @classmethod
  def task_type(cls):
    return CoursierResolve

  def setUp(self):
    super(CoursierResolveTest, self).setUp()
    self.set_options(execution_strategy=NailgunTask.ExecutionStrategy.subprocess)
    self.set_options_for_scope('cache.{}'.format(self.options_scope),
                               read_from=None,
                               write_to=None)
    self.set_options_for_scope('resolver', resolver='coursier')

  def _cache_dir_regex(self, cache_type):
    # One component for the task name, and one for the version.
    return re.compile(r'\.pants\.d/[^/]+/[a-f0-9]+/cache/' + cache_type + '/')

  def resolve(self, targets):
    """Given some targets, execute a resolve, and return the resulting compile_classpath."""
    context = self.context(target_roots=targets)
    self.execute(context)
    return context.products.get_data('compile_classpath')

  def test_resolve_specific(self):
    # Create a jar_library with a single dep, and another library with no deps.
    dep = JarDependency('commons-lang', 'commons-lang', '2.5')
    jar_lib = self.make_target('//:a', JarLibrary, jars=[dep])
    scala_lib = self.make_target('//:b', JavaLibrary, sources=[])
    # Confirm that the deps were added to the appropriate targets.
    compile_classpath = self.resolve([jar_lib, scala_lib])
    self.assertEqual(1, len(compile_classpath.get_for_target(jar_lib)))
    self.assertEqual(0, len(compile_classpath.get_for_target(scala_lib)))
    
  def test_resolve_with_remote_url(self):
    dep_with_url = JarDependency('a', 'b', 'c',
                                 url='http://central.maven.org/maven2/junit/junit/4.12/junit-4.12.jar')
    dep_with_url_lib = self.make_target('//:a', JarLibrary, jars=[dep_with_url])
    
    compile_classpath = self.resolve([dep_with_url_lib])
    # Get paths on compile classpath and assert that it starts with '.../coursier/cache/relative'
    paths = [tup[1] for tup in compile_classpath.get_for_target(dep_with_url_lib)]
    self.assertTrue(any(self._cache_dir_regex('relative').search(path) for path in paths), str(paths))
  
  def test_resolve_with_local_url(self):
    with temporary_file_path(suffix='.jar') as url:
      dep_with_url = JarDependency('commons-lang', 'commons-lang', '2.5', url='file://' + url)
      dep_with_url_lib = self.make_target('//:a', JarLibrary, jars=[dep_with_url])
      
      compile_classpath = self.resolve([dep_with_url_lib])
      # Get paths on compile classpath and assert that it starts with '.../coursier/cache/absolute'
      paths = [tup[1] for tup in compile_classpath.get_for_target(dep_with_url_lib)]
      self.assertTrue(any(self._cache_dir_regex('absolute').search(path) for path in paths), str(paths))

  def test_resolve_specific_with_sources_javadocs(self):
    # Create a jar_library with a single dep, and another library with no deps.
    dep = JarDependency('commons-lang', 'commons-lang', '2.5')
    jar_lib = self.make_target('//:a', JarLibrary, jars=[dep])
    scala_lib = self.make_target('//:b', JavaLibrary, sources=[])
    with self._temp_workdir() as workdir:
      # Confirm that the deps were added to the appropriate targets.
      context = self.context(target_roots=[jar_lib, scala_lib])
      task = self.prepare_execute(context)
      compile_classpath = context.products.get_data('compile_classpath',
        init_func=ClasspathProducts.init_func(workdir)
      )
      task.resolve([jar_lib, scala_lib], compile_classpath, sources=True, javadoc=True, executor=None)

      # Both javadoc and sources jars are added to the classpath product
      self.assertEqual(['default', 'src_doc', 'src_doc'],
       sorted([c[0] for c in compile_classpath.get_for_target(jar_lib)]))
      self.assertEqual(0, len(compile_classpath.get_for_target(scala_lib)))

  def test_resolve_conflicted(self):
    losing_dep = JarDependency('com.google.guava', 'guava', '16.0')
    winning_dep = JarDependency('com.google.guava', 'guava', '16.0.1')
    losing_lib = self.make_target('//:a', JarLibrary, jars=[losing_dep])
    winning_lib = self.make_target('//:b', JarLibrary, jars=[winning_dep])

    compile_classpath = self.resolve([losing_lib, winning_lib])

    losing_cp = compile_classpath.get_for_target(losing_lib)
    winning_cp = compile_classpath.get_for_target(winning_lib)

    self.assertEqual(losing_cp, winning_cp)

    self.assertEqual(1, len(winning_cp))
    conf, path = winning_cp[0]
    self.assertEqual('default', conf)
    self.assertEqual('guava-16.0.1.jar', os.path.basename(path))

  def test_resolve_ignores_jars_with_rev_left_off(self):
    """If a resolve jar leaves off the rev, we're supposed to get the latest version,
       but coursier doesn't currently support that.
       https://github.com/coursier/coursier/issues/209
    """
    with self.assertRaises(TaskError) as cm:
      jar = JarDependency('com.google.guava', 'guava')
      lib = self.make_target('//:b', JarLibrary, jars=[jar])

      self.resolve([lib])
    self.assertEqual(
      "Undefined revs for jars unsupported by Coursier. "
      "\"jar(org={unicode_literal}'com.google.guava', name={unicode_literal}'guava', "
      "rev=None, classifier=None, ext={unicode_literal}'jar')\"".format(unicode_literal='' if PY3 else 'u'),
      str(cm.exception))

  def test_resolve_multiple_artifacts(self):
    def coordinates_for(cp):
      return {resolved_jar.coordinate for conf, resolved_jar in cp}

    no_classifier = JarDependency('org.apache.commons', 'commons-compress', rev='1.4.1')
    classifier = JarDependency('org.apache.commons', 'commons-compress', rev='1.4.1', classifier='tests')

    self.set_options_for_scope('coursier', fetch_options=['-A', 'jar,bundle,test-jar,maven-plugin,src,doc'])

    no_classifier_lib = self.make_target('//:a', JarLibrary, jars=[no_classifier])
    classifier_lib = self.make_target('//:b', JarLibrary, jars=[classifier])
    classifier_and_no_classifier_lib = self.make_target('//:c', JarLibrary,
                                                        jars=[classifier, no_classifier])

    compile_classpath = self.resolve([no_classifier_lib,
                                      classifier_lib,
                                      classifier_and_no_classifier_lib])

    no_classifier_cp = compile_classpath.get_classpath_entries_for_targets([no_classifier_lib])
    classifier_cp = compile_classpath.get_classpath_entries_for_targets([classifier_lib])
    classifier_and_no_classifier_cp = compile_classpath.get_classpath_entries_for_targets(
      classifier_and_no_classifier_lib.closure(bfs=True))

    classifier_and_no_classifier_coords = coordinates_for(classifier_and_no_classifier_cp)

    self.assertIn(no_classifier.coordinate, classifier_and_no_classifier_coords)
    self.assertIn(classifier.coordinate, classifier_and_no_classifier_coords)

    self.assertNotIn(classifier.coordinate, coordinates_for(no_classifier_cp))
    self.assertIn(no_classifier.coordinate, coordinates_for(no_classifier_cp))

    self.assertNotIn(no_classifier.coordinate, coordinates_for(classifier_cp))
    self.assertIn(classifier.coordinate, coordinates_for(classifier_cp))

  def test_excludes_in_java_lib_excludes_all_from_jar_lib(self):
    junit_jar_lib = self._make_junit_target()

    excluding_target = self.make_target('//:b', JavaLibrary, sources=[],
                                        excludes=[Exclude('junit', 'junit')])
    compile_classpath = self.resolve([junit_jar_lib, excluding_target])

    junit_jar_cp = compile_classpath.get_for_target(junit_jar_lib)
    excluding_cp = compile_classpath.get_for_target(excluding_target)

    self.assertEqual(2, len(junit_jar_cp))
    self.assertEqual(0, len(excluding_cp))

    def get_coord_in_classpath(cp, targets):
      """
      Get the simple coords that are going to be on the classpath
      """
      conf_art_tuples_ex = cp.get_classpath_entries_for_targets(targets)
      simple_coords = {x[1].coordinate.simple_coord for x in conf_art_tuples_ex}
      return simple_coords

    # If we grab the transitive closure of the coordinates just for junit, then
    # both junit and hamcrest should be in it.
    simple_coords = get_coord_in_classpath(compile_classpath, [junit_jar_lib])
    self.assertIn('junit:junit:4.12', simple_coords)
    self.assertIn('org.hamcrest:hamcrest-core:1.3', simple_coords)

    # If we grab transitive closure of the coordinates for junit along with a JavaLibrary
    # target that excludes junit, then junit should not be on the classpath.
    simple_coords = get_coord_in_classpath(compile_classpath, [excluding_target, junit_jar_lib])
    self.assertNotIn('junit:junit:4.12', simple_coords)
    self.assertIn('org.hamcrest:hamcrest-core:1.3', simple_coords)

  def test_resolve_no_deps(self):
    # Resolve a library with no deps, and confirm that the empty product is created.
    target = self.make_target('//:a', JavaLibrary, sources=[])
    self.assertTrue(self.resolve([target]))

  def test_second_noop_does_not_invoke_coursier(self):
    junit_jar_lib = self._make_junit_target()
    with self._temp_workdir():
      # Initial resolve does a resolve and populates elements.
      initial_context = self.context(target_roots=[junit_jar_lib])
      task = self.execute(initial_context)

      # If self.runjava has been called, that means coursier is called
      task.runjava = MagicMock()
      task.execute()
      task.runjava.assert_not_called()

  def test_when_invalid_hardlink_and_coursier_cache_should_trigger_resolve(self):
    jar_lib = self._make_junit_target()
    with self._temp_workdir():
      with temporary_dir() as couriser_cache_dir:
        self.set_options_for_scope('coursier', cache_dir=couriser_cache_dir)

        context = self.context(target_roots=[jar_lib])
        task = self.execute(context)
        compile_classpath = context.products.get_data('compile_classpath')

        jar_cp = compile_classpath.get_for_target(jar_lib)

        # └─ junit:junit:4.12
        #    └─ org.hamcrest:hamcrest-core:1.3
        self.assertEqual(2, len(jar_cp))


        # Take a sample jar path, remove it, then call the task again, it should invoke coursier again
        conf, path = jar_cp[0]

        # Remove the hard link under .pants.d/
        safe_rmpath(path)

        # Remove coursier's cache
        safe_rmtree(couriser_cache_dir)

        util.execute_runner = MagicMock()

        # Ignore any error because runjava may fail due to undefined behavior
        try:
          task.execute()
        except TaskError:
          pass

        util.execute_runner.assert_called()

  def test_resolve_jarless_pom(self):
    jar = JarDependency('org.apache.commons', 'commons-weaver-privilizer-parent', '1.3')
    lib = self.make_target('//:b', JarLibrary, jars=[jar])

    compile_classpath = self.resolve([lib])

    lib_cp = compile_classpath.get_for_target(lib)

    self.assertEqual(0, len(lib_cp))

  def _make_junit_target(self):
    junit_dep = JarDependency('junit', 'junit', rev='4.12')
    junit_jar_lib = self.make_target('//:a', JarLibrary, jars=[junit_dep])
    return junit_jar_lib

  @contextmanager
  def _temp_workdir(self):
    old_workdir = self.options['']['pants_workdir']
    with temporary_dir(root_dir=self.build_root) as workdir:
      self.set_options_for_scope('', pants_workdir=workdir)
      self._test_workdir = workdir
      yield workdir
    self._test_workdir = old_workdir
    self.set_options_for_scope('', pants_workdir=old_workdir)


class CoursierResolveFingerprintStrategyTest(TaskTestBase):

  class EmptyTask(Task):
    @classmethod
    def register_options(cls, register):
      register('--a', type=bool, default=False, fingerprint=True)

    @property
    def fingerprint(self):
      # NB: The fake options object doesn't contribute to fingerprinting, so this class redefines
      #     fingerprint.
      if self.get_options().a:
        return "a"
      else:
        return "b"

    def execute(self):
      pass

  @classmethod
  def task_type(cls):
    return cls.EmptyTask

  def setUp(self):
    super(CoursierResolveFingerprintStrategyTest, self).setUp()
    init_subsystem(JarDependencyManagement)

  def tearDown(self):
    super(CoursierResolveFingerprintStrategyTest, self).tearDown()

  def set_artifact_set_for(self, managed_jar_target, artifact_set):
    JarDependencyManagement.global_instance()._artifact_set_map[
      managed_jar_target.id] = artifact_set

  def test_target_target_is_none(self):
    confs = ()
    strategy = CoursierResolveFingerprintStrategy(confs)

    target = self.make_target(':just-target')

    self.assertIsNone(strategy.compute_fingerprint(target))

  def test_jvm_target_without_excludes_is_none(self):
    confs = ()
    strategy = CoursierResolveFingerprintStrategy(confs)

    target_without_excludes = self.make_target(':jvm-target', target_type=JvmTarget)

    self.assertIsNone(strategy.compute_fingerprint(target_without_excludes))

  def test_jvm_target_with_excludes_is_hashed(self):
    confs = ()
    strategy = CoursierResolveFingerprintStrategy(confs)

    target_with_excludes = self.make_target(':jvm-target', target_type=JvmTarget,
                                               excludes=[Exclude('org.some')])

    self.assertIsNotNone(strategy.compute_fingerprint(target_with_excludes))

  def test_jar_library_with_one_jar_is_hashed(self):
    confs = ()
    strategy = CoursierResolveFingerprintStrategy(confs)

    jar_library = self.make_target(':jar-library', target_type=JarLibrary,
                                   jars=[JarDependency('org.some', 'name')])

    self.assertIsNotNone(strategy.compute_fingerprint(jar_library))

  def test_identical_jar_libraries_with_same_jar_dep_management_artifacts_match(self):
    confs = ()
    strategy = CoursierResolveFingerprintStrategy(confs)

    managed_jar_deps = self.make_target(':managed', target_type=ManagedJarDependencies,
                               artifacts=[JarDependency('org.some', 'name')])
    self.set_artifact_set_for(managed_jar_deps, PinnedJarArtifactSet())

    jar_lib_1 = self.make_target(':jar-lib-1', target_type=JarLibrary,
                                   jars=[JarDependency('org.some', 'name')],
                                   managed_dependencies=':managed')


    jar_lib_2 = self.make_target(':jar-lib-2', target_type=JarLibrary,
                              jars=[JarDependency('org.some', 'name')],
                              managed_dependencies=':managed')

    self.assertEqual(strategy.compute_fingerprint(jar_lib_1),
                     strategy.compute_fingerprint(jar_lib_2))

  def test_identical_jar_libraries_with_differing_managed_deps_differ(self):
    confs = ()
    strategy = CoursierResolveFingerprintStrategy(confs)

    managed_jar_deps = self.make_target(':managed', target_type=ManagedJarDependencies,
                               artifacts=[JarDependency('org.some', 'name')])
    self.set_artifact_set_for(managed_jar_deps, PinnedJarArtifactSet())

    jar_lib_with_managed_deps = self.make_target(':jar-lib-1', target_type=JarLibrary,
                                   jars=[JarDependency('org.some', 'name')],
                                   managed_dependencies=':managed')


    jar_lib_without_managed_deps = self.make_target(':jar-lib-no-managed-dep',
                                                    target_type=JarLibrary,
                                                    jars=[JarDependency('org.some', 'name')])

    self.assertNotEqual(strategy.compute_fingerprint(jar_lib_with_managed_deps),
                        strategy.compute_fingerprint(jar_lib_without_managed_deps))
