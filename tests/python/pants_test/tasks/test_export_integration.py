# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import json
import os

from pants.base.build_environment import get_buildroot
from pants.base.config import Config
from pants.ivy.bootstrapper import Bootstrapper
from pants.util.contextutil import temporary_dir
from pants_test.pants_run_integration_test import PantsRunIntegrationTest


class ExportIntegrationTest(PantsRunIntegrationTest):
  _resolve_args = [
    'resolve',
    '--resolve-ivy-confs=default',
    '--resolve-ivy-confs=sources',
    '--resolve-ivy-confs=javadoc',
  ]

  def run_export(self, test_target, workdir, extra_args = list()):
    export_out_file = os.path.join(workdir, 'export_out.txt')
    pants_run = self.run_pants_with_workdir(extra_args + [
        'export',
        '--output-file={out_file}'.format(out_file=export_out_file),
        test_target],
        workdir)
    self.assert_success(pants_run)
    self.assertTrue(os.path.exists(export_out_file),
                    msg='Could not find export output file in {out_file}'
                        .format(out_file=export_out_file))
    with open(export_out_file) as json_file:
      json_data = json.load(json_file)
      return json_data

  def test_export_code_gen(self):
    with temporary_dir(root_dir=self.workdir_root()) as workdir:
      test_target = 'examples/tests/java/com/pants/examples/usethrift:usethrift'
      json_data = self.run_export(test_target, workdir)
      thrift_target_name = 'examples.src.thrift.com.pants.examples.precipitation.precipitation-java'
      codegen_target = os.path.join(os.path.relpath(workdir, get_buildroot()),
                                    'gen/thrift/combined/gen-java:%s' % thrift_target_name)
      self.assertIn(codegen_target, json_data.get('targets'))

  def test_export_json_transitive_jar(self):
    with temporary_dir(root_dir=self.workdir_root()) as workdir:
      test_target = 'examples/tests/java/com/pants/examples/usethrift:usethrift'
      json_data = self.run_export(test_target, workdir)
      targets = json_data.get('targets')
      self.assertIn('org.hamcrest:hamcrest-core:1.3', targets[test_target]['libraries'])

  def test_export_jar_path(self):
    with temporary_dir(root_dir=self.workdir_root()) as workdir:
      test_target = 'examples/tests/java/com/pants/examples/usethrift:usethrift'
      json_data = self.run_export(test_target, workdir, self._resolve_args)
      # Hack because Bootstrapper.instance() reads config from cache. Will go away after we plumb
      # options into IvyUtil properly.
      Config.cache(Config.load())
      ivy_cache_dir = Bootstrapper.instance().ivy_cache_dir
      common_lang_lib_info = json_data.get('libraries').get('commons-lang:commons-lang:2.5')
      self.assertIsNotNone(common_lang_lib_info)
      self.assertEquals(
        common_lang_lib_info.get('default'),
        os.path.join(ivy_cache_dir, 'commons-lang/commons-lang/jars/commons-lang-2.5.jar')
      )
      self.assertEquals(
        common_lang_lib_info.get('javadoc'),
        os.path.join(ivy_cache_dir, 'commons-lang/commons-lang/javadocs/commons-lang-2.5-javadoc.jar')
      )
      self.assertEquals(
        common_lang_lib_info.get('sources'),
        os.path.join(ivy_cache_dir, 'commons-lang/commons-lang/sources/commons-lang-2.5-sources.jar')
      )

  def test_dep_map_for_java_sources(self):
    with temporary_dir(root_dir=self.workdir_root()) as workdir:
      test_target = 'examples/src/scala/com/pants/example/scala_with_java_sources'
      json_data = self.run_export(test_target, workdir)
      targets = json_data.get('targets')
      self.assertIn('examples/src/java/com/pants/examples/java_sources:java_sources', targets)

  def test_sources_and_javadocs(self):
    with temporary_dir(root_dir=self.workdir_root()) as workdir:
      test_target = 'examples/src/scala/com/pants/example/scala_with_java_sources'
      json_data = self.run_export(test_target, workdir, self._resolve_args)
      scala_lang_lib = json_data.get('libraries').get('org.scala-lang:scala-library:2.10.4')
      self.assertIsNotNone(scala_lang_lib)
      self.assertIsNotNone(scala_lang_lib['default'])
      self.assertIsNotNone(scala_lang_lib['sources'])
      self.assertIsNotNone(scala_lang_lib['javadoc'])
