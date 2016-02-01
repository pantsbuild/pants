# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
from textwrap import dedent

from pants.backend.codegen.register import build_file_aliases as register_codegen
from pants.backend.jvm.register import build_file_aliases as register_jvm
from pants.backend.jvm.targets.java_library import JavaLibrary
from pants.backend.project_info.tasks.filedeps import FileDeps
from pants.build_graph.register import build_file_aliases as register_core
from pants_test.tasks.task_test_base import ConsoleTaskTestBase


class FileDepsTest(ConsoleTaskTestBase):

  @property
  def alias_groups(self):
    return register_core().merge(register_jvm()).merge(register_codegen())

  @classmethod
  def task_type(cls):
    return FileDeps

  def setUp(self):
    super(FileDepsTest, self).setUp()
    self.context(options={
      'scala-platform': {
        'runtime': ['tools:scala-library']
      }
    })

    # TODO(John Sirois): Rationalize much of this target emission setup.  Lots of tests do similar
    # things: https://github.com/pantsbuild/pants/issues/525
    def create_target(path, definition, sources=None):
      if sources:
        self.create_files(path, sources)
      self.add_to_build_file(path, definition)

    create_target(path='src/scala/core',
                  definition=dedent("""
                    scala_library(
                      name='core',
                      sources=[
                        'core1.scala'
                      ],
                      java_sources=[
                        'src/java/core'
                      ]
                    )
                  """),
                  sources=['core1.scala'])

    create_target(path='src/java/core',
                  definition=dedent("""
                    java_library(
                      name='core',
                      sources=globs(
                        'core*.java',
                      ),
                      dependencies=[
                        'src/scala/core'
                      ]
                    )
                  """),
                  sources=['core1.java', 'core2.java'])

    create_target(path='src/resources/lib',
                  definition=dedent("""
                    resources(
                      name='lib',
                      sources=globs('*.json')
                    )
                  """),
                  sources=['data.json'])

    create_target(path='src/thrift/storage',
                  definition=dedent("""
                    java_thrift_library(
                      name='storage',
                      sources=[
                        'data_types.thrift'
                      ]
                    )
                  """),
                  sources=['src/thrift/storage/data_types.thrift'])

    create_target(path='src/java/lib',
                  definition=dedent("""
                    java_library(
                      name='lib',
                      sources=[
                        'lib1.java'
                      ],
                      dependencies=[
                        'src/scala/core',
                        'src/thrift/storage'
                      ],
                      resources=[
                        'src/resources/lib'
                      ]
                    )
                  """),
                  sources=['lib1.java'])

    # Derive a synthetic target from the src/thrift/storage thrift target as-if doing code-gen.
    self.create_file('.pants.d/gen/thrift/java/storage/Angle.java')
    self.make_target(spec='.pants.d/gen/thrift/java/storage',
                     target_type=JavaLibrary,
                     derived_from=self.target('src/thrift/storage'),
                     sources=['Angle.java'])
    synthetic_java_lib = self.target('.pants.d/gen/thrift/java/storage')

    java_lib = self.target('src/java/lib')
    java_lib.inject_dependency(synthetic_java_lib.address)

    create_target(path='src/java/bin',
                  definition=dedent("""
                    jvm_binary(
                      name='bin',
                      source='main.java',
                      main='bin.Main',
                      dependencies=[
                        'src/java/lib'
                      ]
                    )
                  """),
                  sources=['main.java'])

    create_target(path='project',
                  definition=dedent("""
                    jvm_app(
                      name='app',
                      binary='src/java/bin',
                      bundles=[
                        bundle(fileset=['config/app.yaml'])
                      ]
                    )
                  """),
                  sources=['config/app.yaml'])

  def test_resources(self):
    self.assert_console_output(
      'src/resources/lib/BUILD',
      'src/resources/lib/data.json',
      targets=[self.target('src/resources/lib')]
    )

  def test_globs(self):
    self.assert_console_output(
      'src/scala/core/BUILD',
      'src/scala/core/core1.scala',
      'src/java/core/BUILD',
      'src/java/core/core*.java',
      targets=[self.target('src/scala/core')],
      options=dict(globs=True),
    )

  def test_globs_app(self):
    self.assert_console_output(
      'project/config/app.yaml',
      'project/BUILD',
      'src/java/bin/BUILD',
      'src/java/core/BUILD',
      'src/java/bin/main.java',
      'src/java/core/core*.java',
      'src/java/lib/BUILD',
      'src/java/lib/lib1.java',
      'src/resources/lib/*.json',
      'src/resources/lib/BUILD',
      'src/scala/core/BUILD',
      'src/scala/core/core1.scala',
      'src/thrift/storage/BUILD',
      'src/thrift/storage/data_types.thrift',
      targets=[self.target('project:app')],
      options=dict(globs=True),
    )

  def test_scala_java_cycle_scala_end(self):
    self.assert_console_output(
      'src/scala/core/BUILD',
      'src/scala/core/core1.scala',
      'src/java/core/BUILD',
      'src/java/core/core1.java',
      'src/java/core/core2.java',
      targets=[self.target('src/scala/core')]
    )

  def test_scala_java_cycle_java_end(self):
    self.assert_console_output(
      'src/scala/core/BUILD',
      'src/scala/core/core1.scala',
      'src/java/core/BUILD',
      'src/java/core/core1.java',
      'src/java/core/core2.java',
      targets=[self.target('src/java/core')]
    )

  def test_concrete_only(self):
    self.assert_console_output(
      'src/java/lib/BUILD',
      'src/java/lib/lib1.java',
      'src/thrift/storage/BUILD',
      'src/thrift/storage/data_types.thrift',
      'src/resources/lib/BUILD',
      'src/resources/lib/data.json',
      'src/scala/core/BUILD',
      'src/scala/core/core1.scala',
      'src/java/core/BUILD',
      'src/java/core/core1.java',
      'src/java/core/core2.java',
      targets=[self.target('src/java/lib')]
    )

  def test_jvm_app(self):
    self.assert_console_output(
      'project/BUILD',
      'project/config/app.yaml',
      'src/java/bin/BUILD',
      'src/java/bin/main.java',
      'src/java/lib/BUILD',
      'src/java/lib/lib1.java',
      'src/thrift/storage/BUILD',
      'src/thrift/storage/data_types.thrift',
      'src/resources/lib/BUILD',
      'src/resources/lib/data.json',
      'src/scala/core/BUILD',
      'src/scala/core/core1.scala',
      'src/java/core/BUILD',
      'src/java/core/core1.java',
      'src/java/core/core2.java',
      targets=[self.target('project:app')]
    )

  def assert_console_output(self, *paths, **kwargs):
    abs_paths = [os.path.join(self.build_root, path) for path in paths]
    super(FileDepsTest, self).assert_console_output(*abs_paths, **kwargs)
