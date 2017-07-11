# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.backend.jvm.subsystems.jar_dependency_management import (JarDependencyManagement,
                                                                    JarDependencyManagementSetup)
from pants.backend.jvm.targets.jar_library import JarLibrary
from pants.backend.jvm.targets.managed_jar_dependencies import (ManagedJarDependencies,
                                                                ManagedJarLibraries)
from pants.backend.jvm.targets.unpacked_jars import UnpackedJars
from pants.build_graph.target import Target
from pants.java.jar.jar_dependency import JarDependency
from pants.java.jar.jar_dependency_utils import M2Coordinate
from pants_test.backend.jvm.tasks.jvm_binary_task_test_base import JvmBinaryTaskTestBase
from pants_test.subsystem.subsystem_util import global_subsystem_instance


class TestJarDependencyManagementSetup(JvmBinaryTaskTestBase):

  @classmethod
  def task_type(cls):
    return JarDependencyManagementSetup

  def _init_manager(self, **jar_dependency_management_options):
    options = {JarDependencyManagement.options_scope: jar_dependency_management_options}
    return global_subsystem_instance(JarDependencyManagement, options=options)

  def _single_artifact_set(self, manager, targets):
    sets = manager.targets_by_artifact_set(targets)
    sets = {a: tgts for a, tgts in sets.items()
            if any(isinstance(t, JarLibrary) for t in tgts)}
    if len(sets) != 1:
      raise ValueError('Test expected there to be only one artifact set! {}'.format(sets))
    return next(iter(sets))

  def test_default_target(self):
    default_target = self.make_target(spec='//foo:management',
                                      target_type=ManagedJarDependencies,
                                      artifacts=[
                                        JarDependency(org='foobar', name='foobar', rev='2'),
                                      ])
    jar_library = self.make_target(spec='//foo:library',
                                   target_type=JarLibrary,
                                   jars=[
                                     JarDependency(org='foobar', name='foobar'),
                                   ])
    context = self.context(target_roots=[default_target, jar_library])
    manager = self._init_manager(default_target='//foo:management')
    task = self.create_task(context)
    task.execute()
    artifact_set = manager.for_target(jar_library)
    self.assertFalse(artifact_set is None)
    self.assertEquals('2', artifact_set[M2Coordinate('foobar', 'foobar')].rev)

  def test_bad_default(self):
    jar_library = self.make_target(spec='//foo:library',
                                   target_type=JarLibrary,
                                   jars=[
                                     JarDependency(org='foobar', name='foobar'),
                                   ])
    context = self.context(target_roots=[jar_library])
    self._init_manager(default_target='//foo:nonexistant')
    task = self.create_task(context)
    with self.assertRaises(JarDependencyManagementSetup.InvalidDefaultTarget):
      task.execute()

  def test_no_default_target(self):
    # Loading this into the context just to make sure it isn't erroneously used.
    management_target = self.make_target(spec='//foo:management',
                                         target_type=ManagedJarDependencies,
                                         artifacts=[
                                           JarDependency(org='foobar', name='foobar', rev='2'),
                                         ])
    jar_library = self.make_target(spec='//foo:library',
                                   target_type=JarLibrary,
                                   jars=[
                                     JarDependency(org='foobar', name='foobar'),
                                   ])
    context = self.context(target_roots=[management_target, jar_library])
    manager = self._init_manager()
    task = self.create_task(context)
    task.execute()
    artifact_set = manager.for_target(jar_library)
    self.assertTrue(artifact_set is None)

  def test_explicit_target(self):
    management_target = self.make_target(spec='//foo:management',
                                         target_type=ManagedJarDependencies,
                                         artifacts=[
                                           JarDependency(org='foobar', name='foobar', rev='2'),
                                         ])
    jar_library = self.make_target(spec='//foo:library',
                                   target_type=JarLibrary,
                                   jars=[
                                     JarDependency(org='foobar', name='foobar'),
                                   ],
                                   managed_dependencies='//foo:management')
    context = self.context(target_roots=[management_target, jar_library])
    manager = self._init_manager()
    task = self.create_task(context)
    task.execute()
    artifact_set = manager.for_target(jar_library)
    self.assertFalse(artifact_set is None)
    self.assertEquals('2', artifact_set[M2Coordinate('foobar', 'foobar')].rev)

  def test_explicit_and_default_target(self):
    default_target = self.make_target(spec='//foo:foobar',
                                      target_type=ManagedJarDependencies,
                                      artifacts=[
                                        JarDependency(org='foobar', name='foobar', rev='2'),
                                      ])
    management_target = self.make_target(spec='//foo:management',
                                         target_type=ManagedJarDependencies,
                                         artifacts=[
                                           JarDependency(org='foobar', name='foobar', rev='3'),
                                         ])
    jar_library = self.make_target(spec='//foo:library',
                                   target_type=JarLibrary,
                                   jars=[
                                     JarDependency(org='foobar', name='foobar'),
                                   ],
                                   managed_dependencies='//foo:management')
    context = self.context(target_roots=[default_target, management_target, jar_library])
    manager = self._init_manager(default_target='//foo:management')
    task = self.create_task(context)
    task.execute()
    artifact_set = manager.for_target(jar_library)
    self.assertFalse(artifact_set is None)
    self.assertEquals('3', artifact_set[M2Coordinate('foobar', 'foobar')].rev)

  def test_using_jar_library_address(self):
    pin_jar_library = self.make_target(
      spec='//foo:pinned-library',
      target_type=JarLibrary,
      jars=[
        JarDependency(org='foobar', name='foobar', rev='2'),
      ],
    )
    management_target = self.make_target(spec='//foo:management',
                                         target_type=ManagedJarDependencies,
                                         artifacts=[
                                           '//foo:pinned-library',
                                         ])
    jar_library = self.make_target(spec='//foo:library',
                                   target_type=JarLibrary,
                                   jars=[
                                     JarDependency(org='foobar', name='foobar'),
                                   ],
                                   managed_dependencies='//foo:management')
    context = self.context(target_roots=[management_target, jar_library, pin_jar_library])
    manager = self._init_manager()
    task = self.create_task(context)
    task.execute()
    artifact_set = manager.for_target(jar_library)
    self.assertFalse(artifact_set is None)
    self.assertEquals('2', artifact_set[M2Coordinate('foobar', 'foobar')].rev)

  def test_duplicate_coord_error(self):
    management_target = self.make_target(spec='//foo:management',
                                         target_type=ManagedJarDependencies,
                                         artifacts=[
                                           JarDependency(org='foobar', name='foobar', rev='2'),
                                           JarDependency(org='foobar', name='foobar', rev='3'),
                                         ])
    context = self.context(target_roots=[management_target])
    self._init_manager()
    task = self.create_task(context)
    with self.assertRaises(JarDependencyManagementSetup.DuplicateCoordinateError):
      task.execute()

  def test_missing_version_error(self):
    management_target = self.make_target(spec='//foo:management',
                                         target_type=ManagedJarDependencies,
                                         artifacts=[
                                           JarDependency(org='foobar', name='foobar'),
                                         ])
    context = self.context(target_roots=[management_target])
    self._init_manager()
    task = self.create_task(context)
    with self.assertRaises(JarDependencyManagementSetup.MissingVersion):
      task.execute()

  def test_duplicate_coord_error_jar(self):
    jar_library = self.make_target(spec='//foo:library',
                                   target_type=JarLibrary,
                                   jars=[
                                     JarDependency(org='foobar', name='foobar', rev='3'),
                                   ])
    management_target = self.make_target(spec='//foo:management',
                                         target_type=ManagedJarDependencies,
                                         artifacts=[
                                           JarDependency(org='foobar', name='foobar', rev='2'),
                                           '//foo:library',
                                         ])
    context = self.context(target_roots=[jar_library, management_target])
    self._init_manager()
    task = self.create_task(context)
    with self.assertRaises(JarDependencyManagementSetup.DuplicateCoordinateError):
      task.execute()

  def test_missing_version_error_jar(self):
    jar_library = self.make_target(spec='//foo:library',
                                   target_type=JarLibrary,
                                   jars=[
                                     JarDependency(org='foobar', name='foobar', rev=None),
                                   ])
    management_target = self.make_target(spec='//foo:management',
                                         target_type=ManagedJarDependencies,
                                         artifacts=[
                                           JarDependency(org='foobar', name='foobar', rev='2'),
                                           '//foo:library',
                                         ])
    context = self.context(target_roots=[jar_library, management_target])
    self._init_manager()
    task = self.create_task(context)
    with self.assertRaises(JarDependencyManagementSetup.MissingVersion):
      task.execute()

  def test_heterogenous_for_targets(self):
    default_target = self.make_target(spec='//foo:management',
                                      target_type=ManagedJarDependencies,
                                      artifacts=[
                                        JarDependency(org='foobar', name='foobar', rev='2'),
                                      ])
    jar_library1 = self.make_target(spec='//foo:library',
                                    target_type=JarLibrary,
                                    jars=[
                                      JarDependency(org='foobar', name='foobar'),
                                    ])
    jar_library2 = self.make_target(spec='//foo:library2',
                                    target_type=JarLibrary,
                                    jars=[
                                      JarDependency(org='vegetables', name='potato', rev='3'),
                                    ])
    unpacked_target = self.make_target(spec='//foo:unpacked',
                                       target_type=UnpackedJars,
                                       libraries=[
                                         ':library2',
                                       ])
    context = self.context(target_roots=[default_target, jar_library1, jar_library2,
                                         unpacked_target])
    manager = self._init_manager(default_target='//foo:management')
    task = self.create_task(context)
    task.execute()
    artifact_set = self._single_artifact_set(manager, [jar_library1, jar_library2,
                                                       unpacked_target])
    self.assertFalse(artifact_set is None)
    self.assertEquals('2', artifact_set[M2Coordinate('foobar', 'foobar')].rev)

  def test_indirection(self):
    management_target = self.make_target(
      target_type=ManagedJarDependencies,
      spec='//foo:management_indirect',
      artifacts=[
        JarDependency(org='foobar', name='foobar', rev='2'),
      ],
    )
    default_target = self.make_target(
      target_type=Target,
      spec='//foo:management',
      dependencies=[
        management_target,
      ],
    )
    jar_library1 = self.make_target(
      target_type=JarLibrary,
      spec='//foo:library',
      jars=[
        JarDependency(org='foobar', name='foobar'),
      ],
    )
    context = self.context(target_roots=[default_target, jar_library1, management_target])
    manager = self._init_manager(default_target='//foo:management')
    task = self.create_task(context)
    task.execute()
    artifact_set = self._single_artifact_set(manager, [jar_library1])
    self.assertFalse(artifact_set is None)
    self.assertEquals('2', artifact_set[M2Coordinate('foobar', 'foobar')].rev)

  def test_invalid_managed_jar_libraries(self):
    target_aliases = {
      'managed_jar_dependencies': ManagedJarDependencies,
      'jar_library': JarLibrary,
    }

    class FakeContext(object):
      def create_object(fake, target_type, name, **kwargs):
        return self.make_target(target_type=target_aliases[target_type],
                                spec='//foo:{}'.format(name), **kwargs)

    with self.assertRaises(ManagedJarLibraries.JarLibraryNameCollision):
      ManagedJarLibraries(FakeContext())(
        name='management',
        artifacts=[
          JarDependency(org='fruit.apple', name='orange', rev='2'),
          JarDependency(org='fruit', name='apple', rev='2', classifier='orange'),
        ],
      )

  def test_simple_dependency_override(self):
    management_target = self.make_target(
      target_type=ManagedJarDependencies,
      spec='//foo:management_indirect',
      artifacts=[
        JarDependency(org='foobar', name='foobar', rev='2'),
        JarDependency(org='barfoo', name='barfoo', rev='1'),
        JarDependency(org='foobar', name='foobar', rev='7', ext='tar'),
      ],
    )
    default_target = self.make_target(
      target_type=ManagedJarDependencies,
      spec='//foo:management',
      artifacts=[
        JarDependency(org='foobar', name='foobar', rev='3'),
        JarDependency(org='fruit', name='apple', rev='4'),
      ],
      dependencies=[
        management_target,
      ],
    )
    jar_library1 = self.make_target(
      target_type=JarLibrary,
      spec='//foo:library',
      jars=[
        JarDependency(org='foobar', name='foobar'),
      ],
    )

    def check_task_execution(manager):
      context = self.context(target_roots=[default_target, jar_library1, management_target])
      task = self.create_task(context)
      task.execute()
      artifact_set = self._single_artifact_set(manager, [jar_library1])
      self.assertFalse(artifact_set is None)
      self.assertEquals('3', artifact_set[M2Coordinate('foobar', 'foobar')].rev)
      self.assertEquals('1', artifact_set[M2Coordinate('barfoo', 'barfoo')].rev)
      self.assertEquals('4', artifact_set[M2Coordinate('fruit', 'apple')].rev)
      self.assertEquals('7', artifact_set[M2Coordinate('foobar', 'foobar', ext='tar')].rev)

    manager = self._init_manager(default_target='//foo:management')
    with self.assertRaises(JarDependencyManagementSetup.IllegalVersionOverride):
      check_task_execution(manager)

  def test_double_dependency_override(self):
    management_target = self.make_target(
      target_type=ManagedJarDependencies,
      spec='//foo:management_indirect',
      artifacts=[
        JarDependency(org='foobar', name='foobar', rev='2'),
        JarDependency(org='barfoo', name='barfoo', rev='1'),
        JarDependency(org='foobar', name='foobar', rev='7', ext='tar'),
      ],
    )
    management_target2 = self.make_target(
      target_type=ManagedJarDependencies,
      spec='//foo:management_indirect2',
      artifacts=[
        JarDependency(org='foobar', name='foobar', rev='7', ext='tar'),
      ],
    )
    indirection_2 = self.make_target(
      target_type=Target,
      spec='//foo:indirection_2',
      dependencies=[
        management_target2,
      ],
    )
    default_target = self.make_target(
      target_type=ManagedJarDependencies,
      spec='//foo:management',
      artifacts=[
        JarDependency(org='foobar', name='foobar', rev='3'),
        JarDependency(org='fruit', name='apple', rev='4'),
      ],
      dependencies=[
        management_target,
        indirection_2,
      ],
    )
    jar_library1 = self.make_target(
      target_type=JarLibrary,
      spec='//foo:library',
      jars=[
        JarDependency(org='foobar', name='foobar'),
      ],
    )

    def check_task_execution(manager):
      context = self.context(target_roots=[default_target, jar_library1, management_target,
                                           management_target2, indirection_2])
      task = self.create_task(context)
      task.execute()
      artifact_set = self._single_artifact_set(manager, [jar_library1])
      self.assertFalse(artifact_set is None)
      self.assertEquals('3', artifact_set[M2Coordinate('foobar', 'foobar')].rev)
      self.assertEquals('1', artifact_set[M2Coordinate('barfoo', 'barfoo')].rev)
      self.assertEquals('4', artifact_set[M2Coordinate('fruit', 'apple')].rev)
      self.assertEquals('7', artifact_set[M2Coordinate('foobar', 'foobar', ext='tar')].rev)

    manager = self._init_manager(default_target='//foo:management')
    with self.assertRaises(JarDependencyManagementSetup.IllegalVersionOverride):
      check_task_execution(manager)
