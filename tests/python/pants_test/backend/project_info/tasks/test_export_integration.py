# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import json
import os
import re

from twitter.common.collections import maybe_list

from pants.base.build_environment import get_buildroot
from pants.ivy.ivy_subsystem import IvySubsystem
from pants_test.backend.project_info.tasks.resolve_jars_test_mixin import ResolveJarsTestMixin
from pants_test.pants_run_integration_test import PantsRunIntegrationTest
from pants_test.subsystem.subsystem_util import subsystem_instance


class ExportIntegrationTest(ResolveJarsTestMixin, PantsRunIntegrationTest):
  _confs_args = [
    '--export-libraries-sources',
    '--export-libraries-javadocs',
  ]

  def run_export(self, test_target, workdir, load_libs=False, only_default=False, extra_args=None):
    """Runs ./pants export ... and returns its json output.

    :param string test_target: spec of the target to run on.
    :param string workdir: working directory to run pants with.
    :param bool load_libs: whether to load external libraries (of any conf).
    :param bool only_default: if loading libraries, whether to only resolve the default conf, or to
      additionally resolve sources and javadocs.
    :param list extra_args: list of extra arguments for the pants invocation.
    :return: the json output of the console task.
    :rtype: dict
    """
    export_out_file = os.path.join(workdir, 'export_out.txt')
    args = ['export',
            '--output-file={out_file}'.format(out_file=export_out_file)] + maybe_list(test_target)
    libs_args = ['--no-export-libraries'] if not load_libs else self._confs_args
    if load_libs and only_default:
      libs_args = []
    pants_run = self.run_pants_with_workdir(args + libs_args + (extra_args or []), workdir)
    self.assert_success(pants_run)
    self.assertTrue(os.path.exists(export_out_file),
                    msg='Could not find export output file in {out_file}'
                        .format(out_file=export_out_file))
    with open(export_out_file) as json_file:
      json_data = json.load(json_file)
      if not load_libs:
        self.assertIsNone(json_data.get('libraries'))
      return json_data

  def evaluate_subtask(self, targets, workdir, load_extra_confs, extra_args, expected_jars):
    json_data = self.run_export(targets, workdir, load_libs=True, only_default=not load_extra_confs,
                                extra_args=extra_args)
    for jar in expected_jars:
      self.assertIn(jar, json_data['libraries'])
      for path in json_data['libraries'][jar].values():
        self.assertTrue(os.path.exists(path), 'Expected jar at {} to actually exist.'.format(path))

  def test_export_code_gen(self):
    with self.temporary_workdir() as workdir:
      test_target = 'examples/tests/java/org/pantsbuild/example/usethrift:usethrift'
      json_data = self.run_export(test_target, workdir, load_libs=True)
      thrift_target_name = ('examples.src.thrift.org.pantsbuild.example.precipitation'
                            '.precipitation-java')
      codegen_target_regex = os.path.join(os.path.relpath(workdir, get_buildroot()),
                                          'gen/thrift/[^/:]*/[^/:]*:{0}'.format(thrift_target_name))
      p = re.compile(codegen_target_regex)
      self.assertTrue(any(p.match(target) for target in json_data.get('targets').keys()))

  def test_export_json_transitive_jar(self):
    with self.temporary_workdir() as workdir:
      test_target = 'examples/tests/java/org/pantsbuild/example/usethrift:usethrift'
      json_data = self.run_export(test_target, workdir, load_libs=True)
      targets = json_data.get('targets')
      self.assertIn('org.hamcrest:hamcrest-core:1.3', targets[test_target]['libraries'])

  def test_export_jar_path_with_excludes(self):
    with self.temporary_workdir() as workdir:
      test_target = 'testprojects/src/java/org/pantsbuild/testproject/exclude:foo'
      json_data = self.run_export(test_target, workdir, load_libs=True)
      self.assertIsNone(json_data
                        .get('libraries')
                        .get('com.typesafe.sbt:incremental-compiler:0.13.7'))
      foo_target = (json_data
                    .get('targets')
                    .get('testprojects/src/java/org/pantsbuild/testproject/exclude:foo'))
      self.assertTrue('com.typesafe.sbt:incremental-compiler' in foo_target.get('excludes'))

  def test_export_jar_path_with_excludes_soft(self):
    with self.temporary_workdir() as workdir:
      test_target = 'testprojects/src/java/org/pantsbuild/testproject/exclude:'
      json_data = self.run_export(test_target,
                                  workdir,
                                  load_libs=True,
                                  extra_args=['--resolve-ivy-soft-excludes'])
      self.assertIsNotNone(json_data
                           .get('libraries')
                           .get('com.martiansoftware:nailgun-server:0.9.1'))
      self.assertIsNotNone(json_data.get('libraries').get('org.pantsbuild:jmake:1.3.8-10'))
      foo_target = (json_data
                    .get('targets')
                    .get('testprojects/src/java/org/pantsbuild/testproject/exclude:foo'))
      self.assertTrue('com.typesafe.sbt:incremental-compiler' in foo_target.get('excludes'))
      self.assertTrue('org.pantsbuild' in foo_target.get('excludes'))

  def test_export_jar_path(self):
    with self.temporary_workdir() as workdir:
      test_target = 'examples/tests/java/org/pantsbuild/example/usethrift:usethrift'
      json_data = self.run_export(test_target, workdir, load_libs=True)
      with subsystem_instance(IvySubsystem) as ivy_subsystem:
        ivy_cache_dir = ivy_subsystem.get_options().cache_dir
        common_lang_lib_info = json_data.get('libraries').get('commons-lang:commons-lang:2.5')
        self.assertIsNotNone(common_lang_lib_info)
        self.assertEquals(
          common_lang_lib_info.get('default'),
          os.path.join(ivy_cache_dir, 'commons-lang/commons-lang/jars/commons-lang-2.5.jar')
        )
        self.assertEquals(
          common_lang_lib_info.get('javadoc'),
          os.path.join(ivy_cache_dir,
                       'commons-lang/commons-lang/javadocs/commons-lang-2.5-javadoc.jar')
        )
        self.assertEquals(
          common_lang_lib_info.get('sources'),
          os.path.join(ivy_cache_dir,
                       'commons-lang/commons-lang/sources/commons-lang-2.5-sources.jar')
        )

  def test_dep_map_for_java_sources(self):
    with self.temporary_workdir() as workdir:
      test_target = 'examples/src/scala/org/pantsbuild/example/scala_with_java_sources'
      json_data = self.run_export(test_target, workdir)
      targets = json_data.get('targets')
      self.assertIn('examples/src/java/org/pantsbuild/example/java_sources:java_sources', targets)

  def test_sources_and_javadocs(self):
    with self.temporary_workdir() as workdir:
      test_target = 'examples/src/scala/org/pantsbuild/example/scala_with_java_sources'
      json_data = self.run_export(test_target, workdir, load_libs=True)
      scala_lang_lib = json_data.get('libraries').get('org.scala-lang:scala-library:2.10.4')
      self.assertIsNotNone(scala_lang_lib)
      self.assertIsNotNone(scala_lang_lib['default'])
      self.assertIsNotNone(scala_lang_lib['sources'])
      self.assertIsNotNone(scala_lang_lib['javadoc'])

  def test_ivy_classifiers(self):
    with self.temporary_workdir() as workdir:
      test_target = 'testprojects/tests/java/org/pantsbuild/testproject/ivyclassifier:ivyclassifier'
      json_data = self.run_export(test_target, workdir, load_libs=True)
      with subsystem_instance(IvySubsystem) as ivy_subsystem:
        ivy_cache_dir = ivy_subsystem.get_options().cache_dir
        avro_lib_info = json_data.get('libraries').get('org.apache.avro:avro:1.7.7')
        self.assertIsNotNone(avro_lib_info)
        self.assertEquals(
          avro_lib_info.get('default'),
          os.path.join(ivy_cache_dir, 'org.apache.avro/avro/jars/avro-1.7.7.jar')
        )
        self.assertEquals(
          avro_lib_info.get('tests'),
          os.path.join(ivy_cache_dir, 'org.apache.avro/avro/jars/avro-1.7.7-tests.jar')
        )
        self.assertEquals(
          avro_lib_info.get('javadoc'),
          os.path.join(ivy_cache_dir, 'org.apache.avro/avro/javadocs/avro-1.7.7-javadoc.jar')
        )
        self.assertEquals(
          avro_lib_info.get('sources'),
          os.path.join(ivy_cache_dir, 'org.apache.avro/avro/sources/avro-1.7.7-sources.jar')
        )

  def test_distributions_and_platforms(self):
    with self.temporary_workdir() as workdir:
      test_target = 'examples/src/java/org/pantsbuild/example/hello/simple'
      json_data = self.run_export(test_target, workdir, load_libs=False, extra_args=[
        '--jvm-platform-default-platform=java7',
        '--jvm-platform-platforms={'
        ' "java7": {"source": "1.7", "target": "1.7", "args": [ "-X123" ]},'
        ' "java8": {"source": "1.8", "target": "1.8", "args": [ "-X456" ]}'
        '}',
        '--jvm-distributions-paths={'
        ' "macos": [ "/Library/JDK" ],'
        ' "linux": [ "/usr/lib/jdk7", "/usr/lib/jdk8"]'
        '}'
      ])
      self.assertFalse('python_setup' in json_data)
      target_name = 'examples/src/java/org/pantsbuild/example/hello/simple:simple'
      targets = json_data.get('targets')
      self.assertEquals('java7', targets[target_name]['platform'])
      self.assertEquals(
        {
          'darwin': ['/Library/JDK'],
          'linux': ['/usr/lib/jdk7', u'/usr/lib/jdk8'],
        },
        json_data['jvm_distributions'])
      self.assertEquals(
        {
          'default_platform' : 'java7',
          'platforms': {
            'java7': {
              'source_level': '1.7',
              'args': ['-X123'],
              'target_level': '1.7'},
            'java8': {
              'source_level': '1.8',
              'args': ['-X456'],
              'target_level': '1.8'},
          }
        },
        json_data['jvm_platforms'])

  def test_intellij_integration(self):
    with self.temporary_workdir() as workdir:
      targets = ['src/python/::', 'tests/python/pants_test/base::', 'contrib/::']
      excludes = [
        '--exclude-target-regexp=.*go/examples.*',
        '--exclude-target-regexp=.*scrooge/tests/thrift.*',
        '--exclude-target-regexp=.*spindle/tests/thrift.*',
        '--exclude-target-regexp=.*spindle/tests/jvm.*'
      ]
      json_data = self.run_export(targets, workdir, extra_args=excludes)

      python_setup = json_data['python_setup']
      self.assertIsNotNone(python_setup)
      self.assertIsNotNone(python_setup['interpreters'])

      default_interpreter = python_setup['default_interpreter']
      self.assertIsNotNone(default_interpreter)
      self.assertIsNotNone(python_setup['interpreters'][default_interpreter])
      self.assertTrue(os.path.exists(python_setup['interpreters'][default_interpreter]['binary']))
      self.assertTrue(os.path.exists(python_setup['interpreters'][default_interpreter]['chroot']))

      core_target = json_data['targets']['src/python/pants/backend/core:core']
      self.assertIsNotNone(core_target)
      self.assertEquals(default_interpreter, core_target['python_interpreter'])
