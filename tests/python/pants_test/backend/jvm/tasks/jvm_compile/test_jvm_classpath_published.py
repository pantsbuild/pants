# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pants.backend.jvm.targets.java_library import JavaLibrary
from pants.backend.jvm.tasks.classpath_products import ClasspathProducts
from pants.backend.jvm.tasks.jvm_compile.jvm_classpath_publisher import RuntimeClasspathPublisher
from pants.util.contextutil import temporary_dir
from pants.util.dirutil import safe_open, touch
from pants_test.tasks.task_test_base import TaskTestBase


class RuntimeClasspathPublisherTest(TaskTestBase):
  @classmethod
  def task_type(cls):
    return RuntimeClasspathPublisher

  def test_incremental_caching(self):
    with temporary_dir(root_dir=self.pants_workdir) as jar_dir, \
         temporary_dir(root_dir=self.pants_workdir) as dist_dir:
      self.set_options(pants_distdir=dist_dir)

      target = self.make_target(
        'java/classpath:java_lib',
        target_type=JavaLibrary,
        sources=['com/foo/Bar.java'],
      )
      context = self.context(target_roots=[target])
      runtime_classpath = context.products.get_data('runtime_classpath', init_func=ClasspathProducts.init_func(self.pants_workdir))
      task = self.create_task(context)

      target_classpath_output = os.path.join(dist_dir, self.options_scope, 'java', 'classpath', 'java_lib')

      # Create a classpath entry.
      touch(os.path.join(jar_dir, 'z1.jar'))
      runtime_classpath.add_for_target(target, [(None, os.path.join(jar_dir, 'z1.jar'))])
      task.execute()
      # Check only one symlink and classpath.txt were created.
      self.assertEqual(len(os.listdir(target_classpath_output)), 2)
      self.assertEqual(
        os.path.realpath(os.path.join(target_classpath_output, sorted(os.listdir(target_classpath_output))[0])),
        os.path.join(jar_dir, 'z1.jar')
      )

      # Remove the classpath entry.
      runtime_classpath.remove_for_target(target, [(None, os.path.join(jar_dir, 'z1.jar'))])

      # Add a different classpath entry
      touch(os.path.join(jar_dir, 'z2.jar'))
      runtime_classpath.add_for_target(target, [(None, os.path.join(jar_dir, 'z2.jar'))])
      task.execute()
      # Check the symlink was updated.
      self.assertEqual(len(os.listdir(target_classpath_output)), 2)
      self.assertEqual(
        os.path.realpath(os.path.join(target_classpath_output, sorted(os.listdir(target_classpath_output))[0])),
        os.path.join(jar_dir, 'z2.jar')
      )

      # Add a different classpath entry
      touch(os.path.join(jar_dir, 'z3.jar'))
      runtime_classpath.add_for_target(target, [(None, os.path.join(jar_dir, 'z3.jar'))])
      task.execute()
      self.assertEqual(len(os.listdir(target_classpath_output)), 3)

      classpath = sorted(os.listdir(target_classpath_output))[2]
      with safe_open(os.path.join(target_classpath_output, classpath)) as classpath_file:
        # Assert there is only one line ending with a newline
        self.assertListEqual(
          classpath_file.readlines(),
          [
            os.pathsep.join([os.path.join(jar_dir, 'z2.jar'), os.path.join(jar_dir, 'z3.jar')]) + '\n'
          ]
        )
