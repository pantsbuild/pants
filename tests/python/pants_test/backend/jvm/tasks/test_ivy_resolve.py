# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from twitter.common.collections import OrderedSet

from pants.backend.jvm.ivy_utils import IvyInfo, IvyModule, IvyModuleRef
from pants.backend.jvm.targets.exclude import Exclude
from pants.backend.jvm.targets.jar_dependency import JarDependency
from pants.backend.jvm.targets.jar_library import JarLibrary
from pants.backend.jvm.targets.java_library import JavaLibrary
from pants.backend.jvm.tasks.ivy_resolve import IvyResolve
from pants.invalidation.cache_manager import VersionedTargetSet
from pants.util.contextutil import temporary_dir
from pants_test.jvm.jvm_tool_task_test_base import JvmToolTaskTestBase


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
  def test_resolve_specific(self):
    # Create a jar_library with a single dep, and another library with no deps.
    dep = JarDependency('commons-lang', 'commons-lang', '2.5')
    jar_lib = self.make_target('//:a', JarLibrary, jars=[dep])
    scala_lib = self.make_target('//:b', JavaLibrary)
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
    context = self.context(target_roots=[losing_lib, winning_lib])

    def artifact_path(name):
      return os.path.join(self.pants_workdir, 'ivy_artifact', name)

    symlink_map = {artifact_path('bogus0'): artifact_path('bogus0'),
                   artifact_path('bogus1'): artifact_path('bogus1'),
                   artifact_path('unused'): artifact_path('unused')}
    task = self.create_task(context, 'unused')

    def mock_ivy_resolve(targets, *args, **kw):
      if targets:
        cache_manager = task.create_cache_manager(False)
        vts = VersionedTargetSet(cache_manager, cache_manager.wrap_targets(targets))
        cache_key = vts.cache_key.hash
      else:
        cache_key = None
      return [], symlink_map, cache_key

    task.ivy_resolve = mock_ivy_resolve

    def mock_parse_report(resolve_hash_name_ignored, conf):
      ivy_info = IvyInfo(conf)

      # Guava 16.0 would be evicted by Guava 16.0.1.  But in a real
      # resolve, it's possible that before it was evicted, it would
      # generate some resolution data.

      artifact_1 = artifact_path('bogus0')
      unused_artifact = artifact_path('unused')

      # Because guava 16.0 was evicted, it has no artifacts
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

      # Add an unrelated module to ensure that it's not returned
      unrelated_parent = IvyModuleRef('com.google.other', 'parent', '1.0')
      unrelated = IvyModule(IvyModuleRef('com.google.unrelated', 'unrelated', '1.0'),
                            unused_artifact, [unrelated_parent])
      ivy_info.add_module(unrelated)

      return ivy_info

    task._parse_report = mock_parse_report
    task.execute()
    compile_classpath = context.products.get_data('compile_classpath', None)
    losing_cp = compile_classpath.get_for_target(losing_lib)
    winning_cp = compile_classpath.get_for_target(winning_lib)
    self.assertEquals(losing_cp, winning_cp)
    self.assertEquals(OrderedSet([(u'default', artifact_path(u'bogus0')),
                                  (u'default', artifact_path(u'bogus1'))]),
                      winning_cp)

  def test_resolve_multiple_artifacts(self):
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

    self.assertIn(no_classifier.coordinate,
                  {resolved_jar.coordinate
                   for conf, resolved_jar in classifier_and_no_classifier_cp})
    self.assertIn(classifier.coordinate,
                  {resolved_jar.coordinate
                   for conf, resolved_jar in classifier_and_no_classifier_cp})

    self.assertNotIn(classifier.coordinate, {resolved_jar.coordinate
                                             for conf, resolved_jar in no_classifier_cp})
    self.assertIn(no_classifier.coordinate, {resolved_jar.coordinate
                                             for conf, resolved_jar in no_classifier_cp})

    self.assertNotIn(no_classifier.coordinate, {resolved_jar.coordinate
                                                for conf, resolved_jar in classifier_cp})
    self.assertIn(classifier.coordinate, {resolved_jar.coordinate
                                          for conf, resolved_jar in classifier_cp})

  def test_excludes_in_java_lib_excludes_all_from_jar_lib(self):
    junit_dep = JarDependency('junit', 'junit', rev='4.12')

    junit_jar_lib = self.make_target('//:a', JarLibrary, jars=[junit_dep])
    excluding_target = self.make_target('//:b', JavaLibrary, excludes=[Exclude('junit', 'junit')])
    compile_classpath = self.resolve([junit_jar_lib, excluding_target])

    junit_jar_cp = compile_classpath.get_for_target(junit_jar_lib)
    excluding_cp = compile_classpath.get_for_target(excluding_target)

    self.assertEquals(0, len(junit_jar_cp))
    self.assertEquals(0, len(excluding_cp))

  def test_resolve_no_deps(self):
    # Resolve a library with no deps, and confirm that the empty product is created.
    target = self.make_target('//:a', JavaLibrary)
    self.assertTrue(self.resolve([target]))

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
