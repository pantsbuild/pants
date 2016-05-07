# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from textwrap import dedent

from pants.backend.codegen.targets.java_protobuf_library import JavaProtobufLibrary
from pants.backend.graph_info.tasks.list_owners import ListOwners
from pants.backend.jvm.targets.jar_dependency import JarDependency
from pants.backend.jvm.targets.jar_library import JarLibrary
from pants.backend.jvm.targets.java_library import JavaLibrary
from pants.backend.jvm.targets.unpacked_jars import UnpackedJars
from pants.backend.python.targets.python_library import PythonLibrary
from pants.base.exceptions import TaskError
from pants.build_graph.build_file_aliases import BuildFileAliases
from pants.build_graph.from_target import FromTarget
from pants.build_graph.prep_command import PrepCommand
from pants.build_graph.resources import Resources
from pants_test.tasks.task_test_base import ConsoleTaskTestBase


class ListOwnersTest(ConsoleTaskTestBase):

  @classmethod
  def task_type(cls):
    return ListOwners

  @property
  def alias_groups(self):
    return BuildFileAliases(
      targets={
        'jar_library': JarLibrary,
        'java_library': JavaLibrary,
        'java_protobuf_library': JavaProtobufLibrary,
        'prep_command': PrepCommand,
        'python_library': PythonLibrary,
        'resources': Resources,
        'unpacked_jars': UnpackedJars,
      },
      context_aware_object_factories={
        'from_target': FromTarget,
      },
      objects={
        'jar': JarDependency,
      }
    )

  def setUp(self):
    super(ListOwnersTest, self).setUp()

    def add_to_build_file(path, name, *sources):
      all_sources = ["'{}'".format(source) for source in list(sources)]
      self.add_to_build_file(path, dedent("""
        python_library(name='{name}',
          sources=[{all_sources}]
          )
        """.format(name=name, all_sources=','.join(all_sources))))

    add_to_build_file('a', 'b', 'b.txt')
    add_to_build_file('a/c', 'd', 'd.txt')
    add_to_build_file('a/c', 'd2', 'd.txt')
    add_to_build_file('a/c', 'e', 'e.txt', 'f.txt', 'g.txt')
    add_to_build_file('a', 'c', 'c/c.txt')
    add_to_build_file('a', 'h', 'c/h.txt')
    add_to_build_file('a/c', 'h', 'h.txt')

  def test_no_targets(self):
    self.assert_console_output(passthru_args=['a/a.txt'])

  def test_no_targets_output_format_json(self):
    self.assert_console_output(dedent("""
      {
          "a/a.txt": []
      }""").lstrip('\n'),
      passthru_args=['a/a.txt'],
      options={'output_format': 'json'}
    )

  def test_one_target(self):
    self.assert_console_output('a:b', passthru_args=['a/b.txt'])

  def test_one_target_output_format_json(self):
    self.assert_console_output(dedent("""
      {
          "a/b.txt": [
              "a:b"
          ]
      }""").lstrip('\n'),
      passthru_args=['a/b.txt'],
      options={'output_format': 'json'}
    )

  def test_multiple_targets(self):
    self.assert_console_output('a/c:d', 'a/c:d2', passthru_args=['a/c/d.txt'])

  def test_multiple_targets_output_format_json(self):
    self.assert_console_output(dedent("""
      {
          "a/c/d.txt": [
              "a/c:d",
              "a/c:d2"
          ]
      }""").lstrip('\n'),
      passthru_args=['a/c/d.txt'],
      options={'output_format': 'json'}
    )

  def test_target_in_parent_directory(self):
    self.assert_console_output('a:c', passthru_args=['a/c/c.txt'])

  def test_multiple_targets_one_in_parent_directory(self):
    self.assert_console_output('a:h', 'a/c:h', passthru_args=['a/c/h.txt'])

  def test_target_with_multiple_sources(self):
    self.assert_console_output('a/c:e', passthru_args=['a/c/e.txt'])

  def test_no_sources(self):
    self.assert_console_raises(TaskError, passthru_args=[])

  def test_too_many_sources_output_format_text(self):
    self.assert_console_raises(TaskError, passthru_args=['a/a.txt', 'a/b.txt'])

  def test_multiple_sources_output_format_json(self):
    self.assert_console_output(dedent("""
      {
          "a/b.txt": [
              "a:b"
          ],
          "a/a.txt": []
      }""").lstrip('\n'),
      passthru_args=['a/a.txt', 'a/b.txt'],
      options={'output_format': 'json'}
    )

  def test_deferred_resources(self):
    PrepCommand.add_goal('compile')
    self.add_to_build_file('root/src/java/prep_resources', dedent("""
      java_library(name='lib',
        resources = [':resources'],
        sources=['Hello.java'],
      )

      resources(name='resources',
        sources = from_target(':compile-prep-command'),
        dependencies = [],
      )

      prep_command(name='compile-prep-command',
        goal='compile',
        prep_executable = 'touch',
        prep_args=['/tmp/prep_command_result']
      )
    """))

    self.assert_console_output(
      'root/src/java/prep_resources:lib',
      passthru_args=['root/src/java/prep_resources/Hello.java']
    )

  def test_deferred_sources(self):
    self.add_to_build_file('root/src/java/prep_sources', dedent("""
        java_protobuf_library(name='proto',
          sources=from_target(':external-source'),
        )

        unpacked_jars(name='external-source',
          libraries=[':external-source-jars'],
          include_patterns=[
            'com/example/testing/**/*.proto',
          ],
        )

        jar_library(name='external-source-jars',
          jars=[
            jar(org='com.example.testing.protolib', name='protolib-external-test', rev='0.0.2'),
          ],
        )
    """))

    self.assert_console_output(
      passthru_args=['root/src/java/prep_sources/com/example/testing/hello.proto']
    )
