# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
from textwrap import dedent

from pants.backend.jvm.targets.jar_dependency import JarDependency
from pants.backend.jvm.targets.jar_library import JarLibrary
from pants.build_graph.build_file_aliases import BuildFileAliases
from pants_test.jvm.jvm_tool_task_test_base import JvmToolTaskTestBase

from pants.contrib.spindle.targets.spindle_thrift_library import SpindleThriftLibrary
from pants.contrib.spindle.tasks.spindle_gen import SpindleGen


class SpindleGenTest(JvmToolTaskTestBase):
  @classmethod
  def task_type(cls):
    return SpindleGen

  @property
  def alias_groups(self):
    return BuildFileAliases(
      targets={
        'spindle_thrift_library': SpindleThriftLibrary,
        'jar_library': JarLibrary,
      },
      objects={
        'jar': JarDependency,
      })

  def test_smoke(self):
    contents = dedent("""namespace java org.pantsbuild.example
      struct Example {
      1: optional i64 number
      }
    """)

    self.create_file(relpath='test_smoke/a.thrift', contents=contents)

    self.add_to_build_file('3rdparty', dedent("""
      jar_library(
        name = 'spindle-runtime',
        jars = [
          jar(org = 'com.foursquare', name = 'spindle-runtime_2.10', rev = '3.0.0-M7'),
        ],
      )
      """
    ))

    self.make_target(spec='test_smoke:a',
                     target_type=SpindleThriftLibrary,
                     sources=['a.thrift'])

    target = self.target('test_smoke:a')
    context = self.context(target_roots=[target])

    task = self.execute(context)

    build_path = os.path.join(task.workdir,
                              'src',
                              'jvm',
                              'org',
                              'pantsbuild',
                              'example')

    java_exists = os.path.isfile(os.path.join(build_path, 'java_a.java'))
    scala_exists = os.path.isfile(os.path.join(build_path, 'a.scala'))
    self.assertTrue(java_exists)
    self.assertTrue(scala_exists)
