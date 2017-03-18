# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
from contextlib import contextmanager

from twitter.common.collections import OrderedSet

from pants.backend.jvm.ivy_utils import IvyInfo, IvyModule, IvyModuleRef, IvyResolveResult
from pants.backend.jvm.subsystems.jar_dependency_management import (JarDependencyManagement,
                                                                    PinnedJarArtifactSet)
from pants.backend.jvm.targets.jar_library import JarLibrary
from pants.backend.jvm.targets.java_library import JavaLibrary
from pants.backend.jvm.targets.jvm_target import JvmTarget
from pants.backend.jvm.targets.managed_jar_dependencies import ManagedJarDependencies
from pants.backend.jvm.tasks.ivy_resolve import IvyResolve
from pants.backend.jvm.tasks.ivy_task_mixin import IvyResolveFingerprintStrategy
from pants.ivy.bootstrapper import Bootstrapper
from pants.java.jar.exclude import Exclude
from pants.java.jar.jar_dependency import JarDependency
from pants.task.task import Task
from pants.util.contextutil import temporary_dir, temporary_file_path
from pants.util.dirutil import safe_delete
from pants_test.jvm.jvm_tool_task_test_base import JvmToolTaskTestBase
from pants_test.subsystem.subsystem_util import init_subsystem
from pants_test.tasks.task_test_base import TaskTestBase, ensure_cached


def strip_workdir(dir, classpath):
  return [(conf, path[len(dir):]) for conf, path in classpath]


class IvyResolveTest(JvmToolTaskTestBase):
  """Tests for the class IvyResolve."""

  @classmethod
  def task_type(cls):
    return IvyResolve

  def setUp(self):
    super(IvyResolveTest, self).setUp()
    self.set_options(use_nailgun=False)
    self.set_options_for_scope('cache.{}'.format(self.options_scope),
                               read_from=None,
                               write_to=None)

  def resolve(self, targets):
    """Given some targets, execute a resolve, and return the resulting compile_classpath."""
    context = self.context(target_roots=targets)
    self.create_task(context).execute()
    return context.products.get_data('compile_classpath')

  #
  # Test section
  #
  @ensure_cached(IvyResolve, expected_num_artifacts=1)
  def test_resolve_specific(self):
    # Create a jar_library with a single dep, and another library with no deps.
    dep = JarDependency('commons-lang', 'commons-lang', '2.5')
    jar_lib = self.make_target('//:a', JarLibrary, jars=[dep])
    scala_lib = self.make_target('//:b', JavaLibrary, sources=[])
    # Confirm that the deps were added to the appropriate targets.
    compile_classpath = self.resolve([jar_lib, scala_lib])
    self.assertEquals(1, len(compile_classpath.get_for_target(jar_lib)))
    self.assertEquals(0, len(compile_classpath.get_for_target(scala_lib)))

  @ensure_cached(IvyResolve, expected_num_artifacts=0)
  def test_resolve_conflicted(self):
    # Create jar_libraries with different versions of the same dep: this will cause
    # a pre-ivy "eviction" in IvyUtils.generate_ivy, but the same case can be triggered
    # due to an ivy eviction where the declared version loses to a transitive version.
    losing_dep = JarDependency('com.google.guava', 'guava', '16.0')
    winning_dep = JarDependency('com.google.guava', 'guava', '16.0.1')
    losing_lib = self.make_target('//:a', JarLibrary, jars=[losing_dep])
    winning_lib = self.make_target('//:b', JarLibrary, jars=[winning_dep])
    # Confirm that the same artifact was added to each target.
    context = self.context(target_roots=[losing_lib, winning_lib])

    def artifact_path(name):
      return os.path.join(self.pants_workdir, 'ivy_artifact', name)

    def mock_ivy_info_for(conf):
      ivy_info = IvyInfo(conf)

      # Guava 16.0 would be evicted by Guava 16.0.1.  But in a real
      # resolve, it's possible that before it was evicted, it would
      # generate some resolution data.

      artifact_1 = artifact_path('bogus0')
      unused_artifact = artifact_path('unused')

      # Because guava 16.0 was evicted, it has no artifacts.
      guava_0 = IvyModule(IvyModuleRef('com.google.guava', 'guava', '16.0'),
                          None, [])
      guava_1 = IvyModule(IvyModuleRef('com.google.guava', 'guava', '16.0.1'),
                          artifact_1, [])
      ivy_info.add_module(guava_0)
      ivy_info.add_module(guava_1)

      artifact_dep_1 = artifact_path('bogus1')

      # Because fake#dep 16.0 was evicted before it was resolved,
      # its deps are never examined, so we don't call add_module.
      guava_dep_0 = IvyModule(IvyModuleRef('com.google.fake', 'dep', '16.0.0'),
                              None, [guava_0.ref])
      guava_dep_1 = IvyModule(IvyModuleRef('com.google.fake', 'dep', '16.0.1'),
                              artifact_dep_1, [guava_1.ref])

      ivy_info.add_module(guava_dep_0)
      ivy_info.add_module(guava_dep_1)

      # Add an unrelated module to ensure that it's not returned.
      unrelated_parent = IvyModuleRef('com.google.other', 'parent', '1.0')
      unrelated = IvyModule(IvyModuleRef('com.google.unrelated', 'unrelated', '1.0'),
                            unused_artifact, [unrelated_parent])
      ivy_info.add_module(unrelated)

      return ivy_info

    symlink_map = {artifact_path('bogus0'): artifact_path('bogus0'),
                   artifact_path('bogus1'): artifact_path('bogus1'),
                   artifact_path('unused'): artifact_path('unused')}
    result = IvyResolveResult([], symlink_map, 'some-key-for-a-and-b', {})
    result._ivy_info_for= mock_ivy_info_for

    def mock_ivy_resolve(*args, **kwargs):
      return result

    task = self.create_task(context, workdir='unused')
    task._ivy_resolve = mock_ivy_resolve

    task.execute()
    compile_classpath = context.products.get_data('compile_classpath', None)
    losing_cp = compile_classpath.get_for_target(losing_lib)
    winning_cp = compile_classpath.get_for_target(winning_lib)
    self.assertEquals(losing_cp, winning_cp)
    self.assertEquals(OrderedSet([(u'default', artifact_path(u'bogus0')),
                                  (u'default', artifact_path(u'bogus1'))]),
                      winning_cp)

  @ensure_cached(IvyResolve, expected_num_artifacts=1)
  def test_resolve_multiple_artifacts(self):
    def coordinates_for(cp):
      return {resolved_jar.coordinate for conf, resolved_jar in cp}

    no_classifier = JarDependency('junit', 'junit', rev='4.12')
    classifier = JarDependency('junit', 'junit', rev='4.12', classifier='sources')

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

  @ensure_cached(IvyResolve, expected_num_artifacts=1)
  def test_excludes_in_java_lib_excludes_all_from_jar_lib(self):
    junit_jar_lib = self._make_junit_target()

    excluding_target = self.make_target('//:b', JavaLibrary, sources=[],
                                        excludes=[Exclude('junit', 'junit')])
    compile_classpath = self.resolve([junit_jar_lib, excluding_target])

    junit_jar_cp = compile_classpath.get_for_target(junit_jar_lib)
    excluding_cp = compile_classpath.get_for_target(excluding_target)

    self.assertEquals(0, len(junit_jar_cp))
    self.assertEquals(0, len(excluding_cp))

  @ensure_cached(IvyResolve, expected_num_artifacts=0)
  def test_resolve_no_deps(self):
    # Resolve a library with no deps, and confirm that the empty product is created.
    target = self.make_target('//:a', JavaLibrary, sources=[])
    self.assertTrue(self.resolve([target]))

  @ensure_cached(IvyResolve, expected_num_artifacts=1)
  def test_resolve_symlinked_cache(self):
    """Test to make sure resolve works when --ivy-cache-dir is a symlinked path.

    When ivy returns the path to a resolved jar file, it might be the realpath to the jar file,
    not the symlink'ed path we are expecting for --ivy-cache-dir.  Make sure that resolve correctly
    recognizes these as belonging in the cache dir and lookups for either the symlinked cache
    dir or the realpath to the cache dir are recognized.
    """
    with temporary_dir() as realcachedir:
      with temporary_dir() as symlinkdir:
        symlink_cache_dir = os.path.join(symlinkdir, 'symlinkedcache')
        os.symlink(realcachedir, symlink_cache_dir)
        self.set_options_for_scope('ivy', cache_dir=symlink_cache_dir)

        dep = JarDependency('commons-lang', 'commons-lang', '2.5')
        jar_lib = self.make_target('//:a', JarLibrary, jars=[dep])
        # Confirm that the deps were added to the appropriate targets.
        compile_classpath = self.resolve([jar_lib])
        self.assertEquals(1, len(compile_classpath.get_for_target(jar_lib)))

  @ensure_cached(IvyResolve, expected_num_artifacts=1)
  def test_ivy_classpath(self):
    # Testing the IvyTaskMixin entry point used by bootstrap for jvm tools.

    junit_jar_lib = self._make_junit_target()

    classpath = self.create_task(self.context()).ivy_classpath([junit_jar_lib])

    self.assertEquals(2, len(classpath))

  def test_second_resolve_reuses_existing_resolution_files(self):
    junit_jar_lib = self._make_junit_target()
    with self._temp_workdir():
      # Initial resolve does a resolve and populates elements.
      initial_context = self.context(target_roots=[junit_jar_lib])
      self.create_task(initial_context).execute()

      # Second resolve should check files and do no ivy call.
      load_context = self.context(target_roots=[junit_jar_lib])
      task = self.create_task(load_context)

      def fail(*arg, **kwargs):
        self.fail("Unexpected call to ivy.")
      task._do_resolve = fail

      task.execute()

      self.assertEqual(initial_context.products.get_data('compile_classpath'),
                       load_context.products.get_data('compile_classpath'))

  def test_when_symlink_cachepath_fails_on_load_due_to_missing_file_trigger_resolve(self):
    jar_lib = self._make_junit_target()
    with self._temp_workdir() as workdir:
      self.resolve([jar_lib])

      # Add pointer to cachepath that points to a non-existent file.
      ivy_resolve_workdir = self._find_resolve_workdir(workdir)
      raw_classpath_path = os.path.join(ivy_resolve_workdir, 'classpath.raw')
      with open(raw_classpath_path, 'a') as raw_f:
        raw_f.write(os.pathsep)
        raw_f.write(os.path.join('non-existent-file'))

      self.resolve([jar_lib])

      # The raw_classpath should be re-created because the previous resolve became invalid.
      with open(raw_classpath_path) as f:
        self.assertNotIn('non-existent-file', f.read())

  def test_fetch_has_same_resolved_jars_as_resolve(self):
    junit_jar_lib = self._make_junit_target()

    with self._temp_cache_dir():
      with self._temp_workdir() as resolve_workdir:
        resolve_classpath = self.resolve([junit_jar_lib])

      # Now do a second resolve with a fresh work directory.
      with self._temp_workdir() as fetch_workdir:
        fetch_classpath = self.resolve([junit_jar_lib])

      self._assert_classpath_equal_for_target(junit_jar_lib,
                                              fetch_classpath, fetch_workdir,
                                              resolve_classpath, resolve_workdir)

  def test_loading_valid_resolve(self):
    junit_jar_lib = self._make_junit_target()

    # Initial resolve does a resolve and populates elements.
    context1 = self.context(target_roots=[junit_jar_lib])
    self.create_task(context1).execute()

    # Second resolve should check files and do no ivy call.
    context2 = self.context(target_roots=[junit_jar_lib])
    task = self.create_task(context2)
    task._do_resolve = self.fail
    task.execute()

    self.assertEqual(context1.products.get_data('compile_classpath'),
                     context2.products.get_data('compile_classpath'))

  def test_invalid_frozen_resolve_file_runs_resolve(self):
    junit_jar_lib = self._make_junit_target()

    with self._temp_workdir() as workdir:
      self.resolve([junit_jar_lib])

      # Find the resolution work dir.
      ivy_workdir = os.path.join(workdir, 'ivy')
      ivy_subdirs = os.listdir(ivy_workdir)
      ivy_subdirs.remove('jars')
      self.assertEqual(1, len(ivy_subdirs))
      resolve_workdir = os.path.join(ivy_workdir, ivy_subdirs[0])

      # Remove a required file for a simple load to force a fetch.
      resolve_report = os.path.join(resolve_workdir, 'resolve-report-default.xml')
      self._assertIsFile(resolve_report)
      safe_delete(resolve_report)

      # Open resolution.json, and make it invalid json.
      frozen_resolve_filename = os.path.join(resolve_workdir, 'resolution.json')
      with open(frozen_resolve_filename, 'w') as f:
        f.write('not json!')

      self.resolve([junit_jar_lib])

      self._assertIsFile(resolve_report)

  def test_after_a_successful_fetch_load_from_fetch(self):
    junit_jar_lib = self._make_junit_target()

    with self._temp_cache_dir():
      with self._temp_workdir():
        self.resolve([junit_jar_lib])

      # Now do a second resolve with a fresh work directory.
      # This will re-use the cached resolve.

      with self._temp_workdir() as fetch_workdir:
        fetch_classpath = self.resolve([junit_jar_lib])
              # We then do a 3rd resolve which will load the results of that fetch rather
              # than redoing the fetch.
        fetch_load_classpath = self.resolve([junit_jar_lib])

        self._assert_classpath_equal_for_target(junit_jar_lib,
                                                fetch_load_classpath, fetch_workdir,
                                                fetch_classpath, fetch_workdir)

  def test_fetch_jar_with_url_specified(self):
    # Resolve a jar with a URL, with fresh ivy cache dirs to ensure that it won't get cached.
    # Run a fetch with a fresh workdir.
    # The fetch should still pick up the correct file.
    with self._temp_cache_dir(), temporary_file_path() as jarfile:
      jar_with_url = JarDependency('org1', 'name1', rev='1234', url='file://{}'.format(jarfile))
      jar_lib = self.make_target('//:a', JarLibrary, jars=[jar_with_url])

      with self._temp_workdir() as workdir, self._temp_ivy_cache_dir():
        self.resolve([jar_lib])
        ivy_resolve_workdir = self._find_resolve_workdir(workdir)

      with self._temp_workdir() as workdir, self._temp_ivy_cache_dir():
        fetch_classpath = self.resolve([jar_lib])

        ivy_resolve_workdir = self._find_resolve_workdir(workdir)

        report_path = os.path.join(ivy_resolve_workdir, 'fetch-report-default.xml')
        self._assertIsFile(report_path)

        _unused_conf, lib_symlink = fetch_classpath.get_for_target(jar_lib)[0]
        with open(jarfile) as jarfile_f:
          with open(lib_symlink) as symlink_f:
            self.assertTrue(jarfile_f.read() == symlink_f.read(),
                            'Expected linked jar and original to match.')

  def test_when_a_report_for_a_conf_is_missing_fall_back_to_fetch(self):
    junit_jar_lib = self._make_junit_target()
    with self._temp_cache_dir():
      with self._temp_workdir():
        self.resolve([junit_jar_lib])

      with self._temp_workdir() as workdir:
        self.resolve([junit_jar_lib])

        # Remove report from workdir.
        ivy_resolve_workdir = self._find_resolve_workdir(workdir)
        report_path = os.path.join(ivy_resolve_workdir, 'fetch-report-default.xml')
        safe_delete(report_path)

        self.resolve([junit_jar_lib])

        self._assertIsFile(report_path)

  def test_when_symlink_cachepath_fails_on_load_due_to_missing_file_trigger_fetch(self):
    jar_lib = self._make_junit_target()

    with self._temp_cache_dir():
      # resolve.
      with self._temp_workdir():
        self.resolve([jar_lib])

      with self._temp_workdir() as workdir:
        # Initial fetch.
        self.resolve([jar_lib])

        # Add pointer to cachepath that points to a non-existent file.
        ivy_resolve_workdir = self._find_resolve_workdir(workdir)
        raw_classpath_path = os.path.join(ivy_resolve_workdir, 'classpath.raw')
        with open(raw_classpath_path, 'a') as raw_f:
          raw_f.write(os.pathsep)
          raw_f.write(os.path.join('non-existent-file'))

        self.resolve([jar_lib])

        # The raw_classpath should be re-created because the previous resolve became invalid.
        with open(raw_classpath_path) as f:
          self.assertNotIn('non-existent-file', f.read())

  def _make_junit_target(self):
    junit_dep = JarDependency('junit', 'junit', rev='4.12')
    junit_jar_lib = self.make_target('//:a', JarLibrary, jars=[junit_dep])
    return junit_jar_lib

  def _find_resolve_workdir(self, workdir):
    ivy_dir = os.path.join(workdir, 'ivy')
    ivy_dir_subdirs = os.listdir(ivy_dir)
    ivy_dir_subdirs.remove('jars')  # Ignore the jars directory.
    self.assertEqual(1, len(ivy_dir_subdirs), 'There should only be the resolve directory.')
    print('>>> got dir {}'.format(ivy_dir_subdirs))
    ivy_resolve_workdir = ivy_dir_subdirs[0]
    return os.path.join(ivy_dir, ivy_resolve_workdir)

  @contextmanager
  def _temp_workdir(self):
    old_workdir = self.options['']['pants_workdir']
    with temporary_dir() as workdir:
      self.set_options_for_scope('', pants_workdir=workdir)
      self._test_workdir = workdir
      yield workdir
    self._test_workdir = old_workdir
    self.set_options_for_scope('', pants_workdir=old_workdir)

  @contextmanager
  def _temp_ivy_cache_dir(self):
    # We also reset the Bootstrapper since it hangs on to a ivy subsystem.
    old_instance = Bootstrapper._INSTANCE
    try:
      with temporary_dir() as ivy_cache_dir:
        Bootstrapper.reset_instance()
        # We set a temp ivy cache to ensure that the ivy we're using won't cache the temporary jar.
        self.set_options_for_scope('ivy', cache_dir=ivy_cache_dir)
        yield ivy_cache_dir
    finally:
      Bootstrapper._INSTANCE = old_instance

  @contextmanager
  def _temp_cache_dir(self):
    with temporary_dir() as cache_dir:
      self.set_options_for_scope('cache.{}'.format(self.options_scope),
                                 read_from=[cache_dir],
                                 write_to=[cache_dir])
      yield

  def _assert_classpath_equal_for_target(self, target, actual_classpath_product, actual_workdir,
                                         expected_classpath_product, expected_workdir):
    self.assertEqual(
      strip_workdir(expected_workdir, expected_classpath_product.get_for_target(target)),
      strip_workdir(actual_workdir, actual_classpath_product.get_for_target(target)))

  def _assertIsFile(self, path):
    self.assertTrue(os.path.isfile(path),
                    'Expected {} to exist as a file'.format(path))


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


class IvyResolveFingerprintStrategyTest(TaskTestBase):

  @classmethod
  def task_type(cls):
    return EmptyTask

  def setUp(self):
    super(IvyResolveFingerprintStrategyTest, self).setUp()
    init_subsystem(JarDependencyManagement)

  def tearDown(self):
    super(IvyResolveFingerprintStrategyTest, self).tearDown()

  def set_artifact_set_for(self, managed_jar_target, artifact_set):
    JarDependencyManagement.global_instance()._artifact_set_map[
      managed_jar_target.id] = artifact_set

  def test_target_target_is_none(self):
    confs = ()
    strategy = IvyResolveFingerprintStrategy(confs)

    target = self.make_target(':just-target')

    self.assertIsNone(strategy.compute_fingerprint(target))

  def test_jvm_target_without_excludes_is_none(self):
    confs = ()
    strategy = IvyResolveFingerprintStrategy(confs)

    target_without_excludes = self.make_target(':jvm-target', target_type=JvmTarget)

    self.assertIsNone(strategy.compute_fingerprint(target_without_excludes))

  def test_jvm_target_with_excludes_is_hashed(self):
    confs = ()
    strategy = IvyResolveFingerprintStrategy(confs)

    target_with_excludes = self.make_target(':jvm-target', target_type=JvmTarget,
                                               excludes=[Exclude('org.some')])

    self.assertIsNotNone(strategy.compute_fingerprint(target_with_excludes))

  def test_jar_library_with_one_jar_is_hashed(self):
    confs = ()
    strategy = IvyResolveFingerprintStrategy(confs)

    jar_library = self.make_target(':jar-library', target_type=JarLibrary,
                                   jars=[JarDependency('org.some', 'name')])

    self.assertIsNotNone(strategy.compute_fingerprint(jar_library))

  def test_identical_jar_libraries_with_same_jar_dep_management_artifacts_match(self):
    confs = ()
    strategy = IvyResolveFingerprintStrategy(confs)

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
    strategy = IvyResolveFingerprintStrategy(confs)

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
