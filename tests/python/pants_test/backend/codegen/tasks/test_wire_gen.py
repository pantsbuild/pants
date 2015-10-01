# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
from textwrap import dedent

from twitter.common.collections import OrderedSet

from pants.backend.codegen.register import build_file_aliases as register_codegen
from pants.backend.codegen.targets.java_wire_library import JavaWireLibrary
from pants.backend.codegen.tasks.wire_gen import WireGen
from pants.backend.core.register import build_file_aliases as register_core
from pants.backend.jvm.targets.exclude import Exclude
from pants.backend.jvm.targets.jar_dependency import JarDependency
from pants.backend.jvm.targets.jar_library import JarLibrary
from pants.base.exceptions import TaskError
from pants.base.revision import Revision
from pants.base.source_root import SourceRoot
from pants.base.validation import assert_list
from pants.build_graph.target import Target
from pants.util.contextutil import temporary_file
from pants_test.tasks.task_test_base import TaskTestBase


class WireGenTest(TaskTestBase):

  EXPECTED_TASK_PATH = ".pants.d/pants_backend_codegen_tasks_wire_gen_WireGen/isolated"

  @classmethod
  def task_type(cls):
    return WireGen

  @property
  def alias_groups(self):
    return register_core().merge(register_codegen())

  def assert_files(self, task, rel_path, contents, service_writer, expected_files):
    assert_list(expected_files)

    with temporary_file() as fp:
      fp.write(contents)
      fp.close()
      self.assertEqual(set(expected_files),
                       task.calculate_genfiles(fp.name, rel_path, service_writer))

  def assert_java_files(self, task, rel_path, contents, service_writer, expected_files):
    self.assert_files(task, rel_path, contents, service_writer, expected_files)

  def test_plain(self):
    task = self.create_task(self.context())
    self.assert_java_files(
      task,
      'temperatures.proto',
      '''
        package org.pantsbuild.example.temperature;

        /**
         * Structure for expressing temperature: 75 Fahrenheit, 12 Celsius, etc.
         * Not so useful on its own.
         */
        message Temperature {
          optional string unit = 1;
          required int64 number = 2;
        }
      ''',
      None,
      ['org/pantsbuild/example/temperature/Temperature.java'])

    self.assert_java_files(
      task,
      'temperatures.proto',
      'package org.pantsbuild.example.temperature',
      None,
      [])

  def test_custom_package(self):
    task = self.create_task(self.context())
    self.assert_java_files(
      task,
      'freds.proto',
      '''
        package com.twitter.ads.revenue_tables;
        option java_package = "com.example.foo.bar";

        message Fred {
          optional string name = 1;
        }
      ''',
      None,
      ['com/example/foo/bar/Fred.java'])

    self.assert_java_files(
      task,
      'bam_bam.proto',
      'option java_package = "com.example.baz.bip";',
      None,
      [])

    self.assert_java_files(
      task,
      'bam_bam.proto',
      '''
        option java_package="com.example.baz.bip" ;

        message BamBam {
          optional string name = 1;
        }
      ''',
      None,
      ['com/example/baz/bip/BamBam.java'])

    self.assert_java_files(
      task,
      'fred.proto',
      '''
        option java_package = "com.example.foo.bar";
        package com.twitter.ads.revenue_tables;

      ''',
      None,
      [])

  def test_service_writer(self):
    task = self.create_task(self.context())
    self.assert_java_files(
      task,
      'pants.proto',
      '''
        package pants.preferences;
        option java_multiple_files = true;
        option java_package = "org.pantsbuild.protos.preferences";
        service SomeService {
          rpc SomeRpc();
          rpc AnotherRpc() {
          }
          rpc AndAnother() {}
        }
      ''',
      'com.squareup.wire.SimpleServiceWriter',
      ['org/pantsbuild/protos/preferences/SomeService.java'])

  def test_calculate_sources(self):
    self.add_to_build_file('wire-lib', dedent('''
      java_wire_library(name='wire-target',
        sources=['foo.proto'],
      )
      '''))
    target = self.target('wire-lib:wire-target')
    context = self.context(target_roots=[target])
    task = self.create_task(context)
    result = task._calculate_sources([target])
    self.assertEquals(1, len(result.keys()))
    self.assertEquals(OrderedSet(['wire-lib/foo.proto']), result['wire-lib'])

  def test_calculate_sources_with_source_root(self):
    SourceRoot.register('project/src/main/wire')
    self.add_to_build_file('project/src/main/wire/wire-lib', dedent('''
      java_wire_library(name='wire-target',
        sources=['foo.proto'],
      )
      '''))
    target = self.target('project/src/main/wire/wire-lib:wire-target')
    context = self.context(target_roots=[target])
    task = self.create_task(context)
    result = task._calculate_sources([target])
    self.assertEquals(1, len(result.keys()))
    self.assertEquals(OrderedSet(['project/src/main/wire/wire-lib/foo.proto']), result['project/src/main/wire'])

  def test_sources_generated_by_target(self):
    root_path = os.path.join('project', 'src', 'main', 'wire')
    wire_path = os.path.join(root_path, 'wire-lib')
    file_path = os.path.join(wire_path, 'org', 'pantsbuild', 'example', 'foo.proto')
    SourceRoot.register(root_path)
    self.add_to_build_file(wire_path, dedent('''
      java_wire_library(name='wire-target',
        sources=['{0}'],
      )
    '''.format(os.path.relpath(file_path, wire_path))))
    self.create_dir(os.path.dirname(file_path))
    self.create_file(file_path, dedent('''
      package org.pantsbuild.example;

      message Foo {
        optional string bar = 1;
        optional string foobar = 2;
      }
    '''))
    target = self.target('project/src/main/wire/wire-lib:wire-target')
    context = self.context(target_roots=[target])
    task = self.create_task(context)
    previous_working_directory = os.path.abspath('.')
    os.chdir(os.path.abspath(self.build_root))
    result = task.sources_generated_by_target(target)
    os.chdir(previous_working_directory)
    self.assertEquals(OrderedSet(['org/pantsbuild/example/Foo.java']), OrderedSet(result))

  def _create_fake_wire_tool(self, version='1.6.0'):
    self.make_target(':wire-compiler', JarLibrary, jars=[
      JarDependency(org='com.squareup.wire', name='wire-compiler', rev=version),
    ])

  def test_compiler_args(self):
    self._create_fake_wire_tool()
    SourceRoot.register('wire-src')
    simple_wire_target = self.make_target('wire-src:simple-wire-target', JavaWireLibrary,
                                          sources=['foo.proto'])
    context = self.context(target_roots=[simple_wire_target])
    task = self.create_task(context)
    self.assertEquals([
      '--java_out={}/{}/wire-src.simple-wire-target'.format(self.build_root,
                                                            self.EXPECTED_TASK_PATH),
      '--proto_path={}/wire-src'.format(self.build_root),
      'foo.proto'],
      task.format_args_for_target(simple_wire_target))

  def test_compiler_args_wirev1(self):
    self._create_fake_wire_tool()
    SourceRoot.register('wire-src')
    wire_targetv1 = self.make_target('wire-src:wire-targetv1', JavaWireLibrary,
                                     sources=['bar.proto'],
                                     service_writer='org.pantsbuild.DummyServiceWriter',
                                     service_writer_options=['opt1', 'opt2'])
    task = self.create_task(self.context(target_roots=[wire_targetv1]))
    self.assertEquals([
      '--java_out={}/{}/wire-src.wire-targetv1'.format(self.build_root, self.EXPECTED_TASK_PATH),
      '--service_writer=org.pantsbuild.DummyServiceWriter',
      '--service_writer_opt', 'opt1',
      '--service_writer_opt', 'opt2',
      '--proto_path={}/wire-src'.format(self.build_root),
      'bar.proto'],
      task.format_args_for_target(wire_targetv1))

  def test_compiler_wire2_with_writer_errors(self):
    self._create_fake_wire_tool(version='2.0.0')
    SourceRoot.register('wire-src')
    wire_targetv1 = self.make_target('wire-src:wire-targetv1', JavaWireLibrary,
                                     sources=['bar.proto'],
                                     service_writer='org.pantsbuild.DummyServiceWriter',
                                     service_writer_options=['opt1', 'opt2'])
    task = self.create_task(self.context(target_roots=[wire_targetv1]))
    with self.assertRaises(TaskError):
      task.format_args_for_target(wire_targetv1)

  def test_compiler_wire1_with_factory_errors(self):
    self._create_fake_wire_tool()
    SourceRoot.register('wire-src')
    wire_targetv2 = self.make_target('wire-src:wire-targetv2', JavaWireLibrary,
                                     sources=['baz.proto'],
                                     service_factory='org.pantsbuild.DummyServiceFactory',
                                     service_factory_options=['v2opt1', 'v2opt2'])
    task = self.create_task(self.context(target_roots=[wire_targetv2]))
    with self.assertRaises(TaskError):
      task.format_args_for_target(wire_targetv2)

  def test_compiler_args_wirev2(self):
    self._create_fake_wire_tool(version='2.0.0')
    SourceRoot.register('wire-src')
    wire_targetv2 = self.make_target('wire-src:wire-targetv2', JavaWireLibrary,
                                     sources=['baz.proto'],
                                     service_factory='org.pantsbuild.DummyServiceFactory',
                                     service_factory_options=['v2opt1', 'v2opt2'])
    task = self.create_task(self.context(target_roots=[wire_targetv2]))
    self.assertEquals([
      '--java_out={}/{}/wire-src.wire-targetv2'.format(self.build_root, self.EXPECTED_TASK_PATH),
      '--service_factory=org.pantsbuild.DummyServiceFactory',
      '--service_factory_opt', 'v2opt1',
      '--service_factory_opt', 'v2opt2',
      '--proto_path={}/wire-src'.format(self.build_root),
      'baz.proto'],
      task.format_args_for_target(wire_targetv2))

  def test_compiler_args_all(self):
    self._create_fake_wire_tool(version='2.0.0')
    SourceRoot.register('wire-src')
    kitchen_sink = self.make_target('wire-src:kitchen-sink', JavaWireLibrary,
                                    sources=['foo.proto', 'bar.proto', 'baz.proto'],
                                    registry_class='org.pantsbuild.Registry',
                                    service_factory='org.pantsbuild.DummyServiceFactory',
                                    no_options=True,
                                    roots=['root1', 'root2', 'root3'],
                                    enum_options=['enum1', 'enum2', 'enum3'],)
    task = self.create_task(self.context(target_roots=[kitchen_sink]))
    self.assertEquals([
      '--java_out={}/{}/wire-src.kitchen-sink'.format(self.build_root, self.EXPECTED_TASK_PATH),
      '--no_options',
      '--service_factory=org.pantsbuild.DummyServiceFactory',
      '--registry_class=org.pantsbuild.Registry',
      '--roots=root1,root2,root3',
      '--enum_options=enum1,enum2,enum3',
      '--proto_path={}/wire-src'.format(self.build_root),
      'foo.proto',
      'bar.proto',
      'baz.proto'],
      task.format_args_for_target(kitchen_sink))

  def test_compiler_args_proto_paths(self):
    self._create_fake_wire_tool(version='2.0.0')
    SourceRoot.register('wire-src')
    SourceRoot.register('wire-other-src')
    parent_target = self.make_target('wire-other-src:parent-target', JavaWireLibrary,
                                     sources=['bar.proto'])
    simple_wire_target = self.make_target('wire-src:simple-wire-target', JavaWireLibrary,
                                          sources=['foo.proto'], dependencies=[parent_target])
    context = self.context(target_roots=[parent_target, simple_wire_target])
    task = self.create_task(context)
    self.assertEquals([
      '--java_out={}/{}/wire-src.simple-wire-target'.format(self.build_root,
                                                            self.EXPECTED_TASK_PATH),
      '--proto_path={}/wire-src'.format(self.build_root),
      '--proto_path={}/wire-other-src'.format(self.build_root),
      'foo.proto'],
      task.format_args_for_target(simple_wire_target))

  def test_wire_compiler_version_robust(self):
    # Here the wire compiler is both indirected, and not 1st in the classpath order.
    guava = self.make_target('3rdparty:guava',
                             JarLibrary,
                             jars=[JarDependency('com.google.guava', 'guava', '18.0')])
    wire = self.make_target('3rdparty:wire',
                            JarLibrary,
                            jars=[
                              JarDependency('com.squareup.wire', 'wire-compiler', '3.0.0',
                                            excludes=[Exclude('com.google.guava', 'guava')])
                            ])
    alias = self.make_target('a/random/long/address:spec', Target, dependencies=[guava, wire])
    self.set_options(wire_compiler='a/random/long/address:spec')
    task = self.create_task(self.context(target_roots=[alias]))
    self.assertEqual(Revision(3, 0, 0), task.wire_compiler_version)

  def test_wire_compiler_version_none(self):
    guava = self.make_target('3rdparty:guava',
                             JarLibrary,
                             jars=[JarDependency('com.google.guava', 'guava', '18.0')])
    self.set_options(wire_compiler='3rdparty:guava')
    task = self.create_task(self.context(target_roots=[guava]))
    with self.assertRaises(task.WireCompilerVersionError):
      task.wire_compiler_version

  def test_wire_compiler_version_conflict(self):
    george = self.make_target('3rdparty:george',
                              JarLibrary,
                              jars=[JarDependency('com.squareup.wire', 'wire-compiler', '3.0.0'),
                                    JarDependency('com.squareup.wire', 'wire-compiler', '1.6.0')])
    self.set_options(wire_compiler='3rdparty:george')
    task = self.create_task(self.context(target_roots=[george]))
    with self.assertRaises(task.WireCompilerVersionError):
      task.wire_compiler_version
