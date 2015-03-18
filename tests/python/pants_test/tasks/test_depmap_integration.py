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


class DepmapIntegrationTest(PantsRunIntegrationTest):

  def run_depmap_project_info(self, test_target, workdir):
    depmap_out_file = os.path.join(workdir, 'depmap_out.txt')
    pants_run = self.run_pants_with_workdir([
        'depmap',
        '--project-info',
        '--output-file={out_file}'.format(out_file=depmap_out_file),
        test_target],
        workdir)
    # Is the above call failing? The --project-info flag is scheduled to be removed
    # after 0.0.31. These tests have already been duplicated to test_export_integration.py
    # so you can just remove this file completely.
    self.assert_success(pants_run)
    self.assertTrue(os.path.exists(depmap_out_file),
                    msg='Could not find depmap output file in {out_file}'
                        .format(out_file=depmap_out_file))
    with open(depmap_out_file) as json_file:
      json_data = json.load(json_file)
      return json_data

  def test_depmap_code_gen(self):
    with temporary_dir(root_dir=self.workdir_root()) as workdir:
      test_target = 'examples/tests/java/com/pants/examples/usethrift:usethrift'
      json_data = self.run_depmap_project_info(test_target, workdir)
      thrift_target_name = 'examples.src.thrift.com.pants.examples.precipitation.precipitation-java'
      codegen_target = os.path.join(os.path.relpath(workdir, get_buildroot()),
                                    'gen/thrift/combined/gen-java:%s' % thrift_target_name)
      self.assertIn(codegen_target, json_data.get('targets'))

  def test_depmap_json_transitive_jar(self):
    with temporary_dir(root_dir=self.workdir_root()) as workdir:
      test_target = 'examples/tests/java/com/pants/examples/usethrift:usethrift'
      json_data = self.run_depmap_project_info(test_target, workdir)
      targets = json_data.get('targets')
      self.assertIn('org.hamcrest:hamcrest-core:1.3', targets[test_target]['libraries'])

  def test_depmap_jar_path(self):
    with temporary_dir(root_dir=self.workdir_root()) as workdir:
      test_target = 'examples/tests/java/com/pants/examples/usethrift:usethrift'
      json_data = self.run_depmap_project_info(test_target, workdir)
      # Hack because Bootstrapper.instance() reads config from cache. Will go away after we plumb
      # options into IvyUtil properly.
      Config.cache(Config.load())
      ivy_cache_dir = Bootstrapper.instance().ivy_cache_dir
      self.assertEquals(json_data.get('libraries').get('commons-lang:commons-lang:2.5'),
                        [os.path.join(ivy_cache_dir,
                                      'commons-lang/commons-lang/jars/commons-lang-2.5.jar')])

  def test_dep_map_for_java_sources(self):
    with temporary_dir(root_dir=self.workdir_root()) as workdir:
      test_target = 'examples/src/scala/com/pants/example/scala_with_java_sources'
      json_data = self.run_depmap_project_info(test_target, workdir)
      targets = json_data.get('targets')
      self.assertIn('examples/src/java/com/pants/examples/java_sources:java_sources', targets)
