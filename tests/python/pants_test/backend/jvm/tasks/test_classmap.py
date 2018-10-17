# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from contextlib import contextmanager

from pants.backend.jvm.tasks.classmap import ClassmapTask
from pants.build_graph.target import Target
from pants.util.contextutil import open_zip
from pants_test.backend.jvm.tasks.jvm_binary_task_test_base import JvmBinaryTaskTestBase
from pants_test.subsystem.subsystem_util import init_subsystem
from pants_test.task_test_base import ConsoleTaskTestBase


class ClassmapTaskTest(ConsoleTaskTestBase, JvmBinaryTaskTestBase):
  @classmethod
  def task_type(cls):
    return ClassmapTask

  def setUp(self):
    super(ClassmapTaskTest, self).setUp()
    init_subsystem(Target.Arguments)

    self.add_to_build_file(
      'a',
      'java_library(sources=["a1.java", "a2.java"])',
    )

    self.jar_artifact = self.create_artifact(org='org.example', name='foo', rev='1.0.0')
    with open_zip(self.jar_artifact.pants_path, 'w') as jar:
      jar.writestr('foo/Foo.class', '')

    self.add_to_build_file(
      'b',
      'jar_library(jars=[jar(org="org.example", name="foo", rev="1.0.0")])',
    )

    self.add_to_build_file(
      'c',
      'java_library(dependencies=["a", "b"])',
    )

    self.target_a = self.target('a')
    self.target_b = self.target('b')
    self.target_c = self.target('c')

  @contextmanager
  def prepare_context(self, options=None):
    def idict(*args):
      return {a: a for a in args}

    options = options or {}
    self.set_options(**options)

    task_context = self.context(target_roots=[self.target_c])
    self.add_to_runtime_classpath(task_context, self.target_a, idict('a1.class', 'a2.class'))
    self.add_to_runtime_classpath(task_context, self.target_c, idict('c1.class', 'c2.class'))

    classpath_products = self.ensure_classpath_products(task_context)
    classpath_products.add_jars_for_targets(targets=[self.target_b],
                                            conf='default',
                                            resolved_jars=[self.jar_artifact])
    yield task_context

  def test_classmap_none(self):
    class_mappings = self.execute_console_task()
    self.assertEqual([], class_mappings)

  def test_classmap(self):
    with self.prepare_context() as context:
      class_mappings = self.execute_console_task_given_context(context)
      class_mappings_expected = ['a1 a:a', 'a2 a:a', 'c1 c:c', 'c2 c:c', 'foo.Foo b:b']
      self.assertEqual(class_mappings_expected, sorted(class_mappings))

  def test_classmap_internal_only(self):
    with self.prepare_context(options={'internal_only': True}) as context:
      class_mappings = self.execute_console_task_given_context(context)
      class_mappings_expected = ['a1 a:a', 'a2 a:a', 'c1 c:c', 'c2 c:c']
      self.assertEqual(class_mappings_expected, sorted(class_mappings))

  def test_classmap_intransitive(self):
    with self.prepare_context(options={'transitive': False}) as context:
      class_mappings = self.execute_console_task_given_context(context)
      class_mappings_expected = ['c1 c:c', 'c2 c:c']
      self.assertEqual(class_mappings_expected, sorted(class_mappings))
