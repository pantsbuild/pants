# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from textwrap import dedent

from twitter.common.collections import OrderedSet

from pants.backend.codegen.register import build_file_aliases as register_codegen
from pants.backend.codegen.tasks.wire_gen import WireGen
from pants.backend.core.register import build_file_aliases as register_core
from pants.base.source_root import SourceRoot
from pants.base.validation import assert_list
from pants.util.contextutil import temporary_file
from pants_test.task_test_base import TaskTestBase


class WireGenTest(TaskTestBase):
  @classmethod
  def task_type(cls):
    return WireGen

  @property
  def alias_groups(self):
    return register_core().merge(register_codegen())

  def assert_files(self, task, lang, rel_path, contents, service_writer, expected_files):
    assert_list(expected_files)

    with temporary_file() as fp:
      fp.write(contents)
      fp.close()
      self.assertEqual(set(expected_files),
                       task.calculate_genfiles(fp.name, rel_path, service_writer)[lang])

  def assert_java_files(self, task, rel_path, contents, service_writer, expected_files):
    self.assert_files(task, 'java', rel_path, contents, service_writer, expected_files)

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
