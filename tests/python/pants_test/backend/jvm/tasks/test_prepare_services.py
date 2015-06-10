# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pants.backend.jvm.targets.exclude import Exclude
from pants.backend.jvm.targets.java_library import JavaLibrary
from pants.backend.jvm.targets.jvm_target import JvmTarget
from pants.backend.jvm.targets.scala_library import ScalaLibrary
from pants.backend.jvm.tasks.prepare_services import PrepareServices
from pants.util.contextutil import temporary_dir
from pants_test.tasks.task_test_base import TaskTestBase


class PrepareServicesTest(TaskTestBase):
  @classmethod
  def task_type(cls):
    return PrepareServices

  def test_find_all_relevant_resources_targets(self):
    jvm_target = self.make_target('jvm:target', target_type=JvmTarget)
    java_library = self.make_target('java:target', target_type=JavaLibrary)
    scala_library = self.make_target('scala:target',
                                     target_type=ScalaLibrary,
                                     services={'com.foo.bars.Baz': ['com.spam.bars.BaxImpl']})
    non_services_target = self.make_target('other:target')

    task = self.create_task(self.context(target_roots=[jvm_target,
                                                       java_library,
                                                       non_services_target,
                                                       scala_library]))
    relevant_resources_targets = task.find_all_relevant_resources_targets()

    # Just the JvmTargets are relevant, and they're relevant whether they have defined services or
    # not.
    self.assertEqual(sorted([jvm_target, java_library, scala_library]),
                     sorted(relevant_resources_targets))

  def test_create_invalidation_strategy(self):
    task = self.create_task(self.context())
    invalidation_strategy = task.create_invalidation_strategy()

    target = self.make_target('java:target',
                              target_type=JavaLibrary,
                              services={'com.foo.bars.Baz': ['com.spam.bars.BaxImplA']})
    fingerprint1 = invalidation_strategy.fingerprint_target(target)
    self.assertIsNotNone(fingerprint1)

    # Removal of services should be detected.
    self.reset_build_graph()
    target = self.make_target('java:target', target_type=JavaLibrary)
    fingerprint2 = invalidation_strategy.fingerprint_target(target)
    self.assertIsNotNone(fingerprint2)
    self.assertNotEqual(fingerprint1, fingerprint2)

    # Target payload should not affect fingerprinting.
    self.reset_build_graph()
    target = self.make_target('java:target',
                              excludes=[Exclude('com.foo', 'fiz')],
                              target_type=JavaLibrary)
    fingerprint3 = invalidation_strategy.fingerprint_target(target)
    self.assertEqual(fingerprint2, fingerprint3)

    # A change in services should be detected.
    self.reset_build_graph()
    target = self.make_target('java:target',
                              target_type=JavaLibrary,
                              services={'com.foo.bars.Baz': ['com.spam.bars.BazImplA',
                                                             'com.spam.bars.BazImplB']})
    fingerprint4 = invalidation_strategy.fingerprint_target(target)
    self.assertIsNotNone(fingerprint4)
    self.assertNotEqual(fingerprint1, fingerprint4)
    self.assertNotEqual(fingerprint2, fingerprint4)

  def test_prepare_resources_none(self):
    task = self.create_task(self.context())

    def assert_no_resources_prepared(target):
      with temporary_dir() as chroot:
        task.prepare_resources(target, chroot)
        self.assertEqual([], os.listdir(chroot))

    assert_no_resources_prepared(self.make_target('java:target', target_type=JavaLibrary))
    assert_no_resources_prepared(self.make_target('scala:target',
                                                  target_type=ScalaLibrary,
                                                  services={}))
    assert_no_resources_prepared(self.make_target('jvm:target',
                                                  target_type=JvmTarget,
                                                  services={'ServiceInterface': []}))

  def test_prepare_resources(self):
    task = self.create_task(self.context())
    target = self.make_target('java:target',
                              target_type=JavaLibrary,
                              services={'ServiceInterfaceA': ['ServiceImplA1, ServiceImplA2'],
                                        'ServiceInterfaceB': [],
                                        'ServiceInterfaceC': ['ServiceImplC1']})
    with temporary_dir() as chroot:
      task.prepare_resources(target, chroot)
      resource_files = {}
      for root, dirs, files in os.walk(chroot):
        for f in files:
          resource_files[f] = os.path.relpath(os.path.join(root, f), chroot)
      self.assertEqual(sorted(os.path.join('META-INF', 'services', svc)
                              for svc in ('ServiceInterfaceA', 'ServiceInterfaceC')),
                       sorted(resource_files.values()))

      def assert_contents(path, services):
        read_services = []
        with open(os.path.join(chroot, path)) as fp:
          for line in fp.readlines():
            line = line.strip()
            if not line.startswith('#'):
              read_services.append(line)
        self.assertEqual(services, read_services)

      assert_contents(resource_files['ServiceInterfaceA'], ['ServiceImplA1, ServiceImplA2'])
      assert_contents(resource_files['ServiceInterfaceC'], ['ServiceImplC1'])

  def test_relative_resource_paths_none(self):
    task = self.create_task(self.context())

    target = self.make_target('java:target', target_type=JavaLibrary)
    relative_resource_paths = task.relative_resource_paths(target, '/chroot/path/does/not/matter')
    self.assertEqual([], relative_resource_paths)

    self.reset_build_graph()
    target = self.make_target('java:target', target_type=JavaLibrary, services={})
    relative_resource_paths = task.relative_resource_paths(target, '/chroot/path/does/not/matter')
    self.assertEqual([], relative_resource_paths)

    self.reset_build_graph()
    target = self.make_target('java:target',
                              target_type=JavaLibrary,
                              services={'ServiceInterface': []})
    relative_resource_paths = task.relative_resource_paths(target, '/chroot/path/does/not/matter')
    self.assertEqual([], relative_resource_paths)

  def test_relative_resource_paths(self):
    task = self.create_task(self.context())
    target = self.make_target('java:target',
                              target_type=JavaLibrary,
                              services={'ServiceInterfaceA': ['ServiceImplA1, ServiceImplA2'],
                                        'ServiceInterfaceB': [],
                                        'ServiceInterfaceC': ['ServiceImplC1']})
    relative_resource_paths = task.relative_resource_paths(target, '/chroot/path/does/not/matter')
    self.assertEqual(sorted(os.path.join('META-INF', 'services', svc)
                            for svc in ('ServiceInterfaceA', 'ServiceInterfaceC')),
                     sorted(relative_resource_paths))
