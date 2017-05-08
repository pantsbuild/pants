# coding=utf-8
# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import shutil

from pants.base.build_environment import get_buildroot
from pants_test.pants_run_integration_test import PantsRunIntegrationTest


class DepExportsIntegrationTest(PantsRunIntegrationTest):

  SRC_PREFIX = 'testprojects/tests'
  SRC_TYPES = ['java', 'scala']
  SRC_PACKAGE = 'org/pantsbuild/testproject/exports'

  @classmethod
  def hermetic(cls):
    return True

  def test_compilation(self):
    for lang in self.SRC_TYPES:
      path = os.path.join(self.SRC_PREFIX, lang, self.SRC_PACKAGE)
      pants_run = self.run_pants(['list', '{}::'.format(path)])
      self.assert_success(pants_run)
      target_list = pants_run.stdout_data.strip().split('\n')
      for target in target_list:
        pants_run = self.run_pants(['compile', '--lint-scalafmt-skip', target])
        self.assert_success(pants_run)

  def modify_exports_and_compile(self, target, modify_file):
    with self.temporary_sourcedir() as tmp_src:
      src_dir = os.path.relpath(os.path.join(tmp_src, os.path.basename(self.SRC_PACKAGE)), get_buildroot())
      target_dir, target_name = target.rsplit(':', 1)
      shutil.copytree(target_dir, src_dir)
      with self.temporary_workdir() as workdir:
        cmd = ['compile', '--lint-scalafmt-skip', '{}:{}'.format(src_dir, target_name)]
        pants_run = self.run_pants_with_workdir(command=cmd, workdir=workdir)
        self.assert_success(pants_run)

        with open(os.path.join(src_dir, modify_file), 'ab') as fh:
          fh.write(b'\n')

        pants_run = self.run_pants_with_workdir(command=cmd, workdir=workdir)
        self.assert_success(pants_run)
        self.assertTrue('{}:{}'.format(src_dir, target_name) in pants_run.stdout_data)

  def test_invalidation(self):
    for lang in self.SRC_TYPES:
      path = os.path.join(self.SRC_PREFIX, lang, self.SRC_PACKAGE)
      target = '{}:D'.format(path)
      self.modify_exports_and_compile(target, 'A.{}'.format(lang))
      self.modify_exports_and_compile(target, 'B.{}'.format(lang))

  def test_non_exports(self):
    pants_run = self.run_pants(['compile', '--lint-scalafmt-skip',
                                'testprojects/tests/scala/org/pantsbuild/testproject/non_exports:C'])
    self.assert_failure(pants_run)
    self.assertIn('FAILURE: Compilation failure: Failed jobs: '
                  'compile(testprojects/tests/scala/org/pantsbuild/testproject/non_exports:C)',
                  pants_run.stdout_data)


class DepExportsThriftTargets(PantsRunIntegrationTest):

  def test_exports_for_thrift_targets(self):
    pants_run = self.run_pants(['compile', 'testprojects/src/thrift/org/pantsbuild/thrift_exports:C-with-exports'])
    self.assert_success(pants_run)

    pants_run = self.run_pants(['compile', 'testprojects/src/thrift/org/pantsbuild/thrift_exports:C-without-exports'])
    self.assert_failure(pants_run)
    self.assertIn('Symbol \'type org.pantsbuild.thrift_exports.thriftscala.FooA\' is missing from the classpath',
                  pants_run.stdout_data)
