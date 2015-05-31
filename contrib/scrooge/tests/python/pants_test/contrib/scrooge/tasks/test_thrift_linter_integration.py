# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pants.util.contextutil import temporary_file
from pants_test.pants_run_integration_test import PantsRunIntegrationTest


class ThriftLinterTest(PantsRunIntegrationTest):
  @staticmethod
  def thrift_test_target(name):
    return 'contrib/scrooge/tests/thrift/org/pantsbuild/contrib/scrooge/thrift_linter:' + name

  def test_good(self):
    # thrift-linter should pass without warnings with correct thrift files.
    cmd = ['thrift-linter', self.thrift_test_target('good-thrift')]
    pants_run = self.run_pants(cmd)
    self.assert_success(pants_run)
    self.assertFalse('Lint errors found!' in pants_run.stdout_data)

  def test_skip_skips_execution(self):
    cmd = ['thrift-linter',
           '--skip',
           '--lint-all-thrift',
           self.thrift_test_target('bad-thrift-strict')]
    pants_run = self.run_pants(cmd)
    self.assert_success(pants_run)
    self.assertFalse('Lint errors found!' in pants_run.stdout_data)

  def test_bad_default(self):
    # thrift-linter fails on linter errors.
    cmd = ['thrift-linter', '--lint-all-thrift', self.thrift_test_target('bad-thrift-default')]
    pants_run = self.run_pants(cmd)
    self.assert_success(pants_run)
    self.assertTrue('Lint errors found!' in pants_run.stdout_data)

  def test_bad_strict(self):
    # thrift-linter fails on linter errors (BUILD target defines thrift_linter_strict=True)
    cmd = ['thrift-linter', '--lint-all-thrift', self.thrift_test_target('bad-thrift-strict')]
    pants_run = self.run_pants(cmd)
    self.assert_failure(pants_run)
    self.assertTrue('Lint errors found!' in pants_run.stdout_data)

  def test_bad_non_strict(self):
    # thrift-linter fails on linter errors (BUILD target defines thrift_linter_strict=False)
    cmd = ['thrift-linter', '--lint-all-thrift', self.thrift_test_target('bad-thrift-non-strict')]
    pants_run = self.run_pants(cmd)
    self.assert_success(pants_run)
    self.assertTrue('Lint errors found!' in pants_run.stdout_data)

  def test_bad_default_override(self):
    # thrift-linter fails with command line flag overriding the BUILD section.
    cmd = ['thrift-linter',
           '--strict',
           '--lint-all-thrift',
           self.thrift_test_target('bad-thrift-default')]
    pants_run = self.run_pants(cmd)
    self.assert_failure(pants_run)
    self.assertTrue('Lint errors found!' in pants_run.stdout_data)

  def test_bad_strict_override(self):
    # thrift-linter passes with non-strict command line flag overriding the BUILD section.
    cmd = ['thrift-linter',
           '--no-strict',
           '--lint-all-thrift',
           self.thrift_test_target('bad-thrift-strict')]
    pants_run = self.run_pants(cmd)
    self.assert_success(pants_run)
    self.assertTrue('Lint errors found!' in pants_run.stdout_data)

  def test_bad_non_strict_override(self):
    # thrift-linter fails with command line flag overriding the BUILD section.
    cmd = ['thrift-linter',
           '--lint-all-thrift',
           '--strict',
           self.thrift_test_target('bad-thrift-non-strict')]
    pants_run = self.run_pants(cmd)
    self.assert_failure(pants_run)
    self.assertTrue('Lint errors found!' in pants_run.stdout_data)

  def test_bad_pants_ini_strict(self):
    # thrift-linter fails if pants.ini has a thrift-linter:strict=True setting
    cmd = ['thrift-linter', '--lint-all-thrift', self.thrift_test_target('bad-thrift-default')]
    pants_ini_config = {'thrift-linter': {'strict': True}}
    pants_run = self.run_pants(cmd, config = pants_ini_config)
    self.assert_failure(pants_run)
    self.assertTrue('Lint errors found!' in pants_run.stdout_data)

  def test_bad_pants_ini_strict_overridden(self):
    # thrift-linter passes if pants.ini has a thrift-linter:strict=True setting and
    # a command line non-strict flag is passed.
    cmd = ['thrift-linter',
           '--no-strict',
           '--lint-all-thrift',
           self.thrift_test_target('bad-thrift-default')]
    pants_ini_config = {'thrift-linter': {'strict': True}}
    pants_run = self.run_pants(cmd, config = pants_ini_config)
    self.assert_success(pants_run)
    self.assertTrue('Lint errors found!' in pants_run.stdout_data)

  def test_linter_runs_on_modified_thrift(self):
    # thrift-linter runs on modified files only by default

    # Before any thrift files are modified
    cmd = ['thrift-linter', self.thrift_test_target('all-thrift')]
    pants_run = self.run_pants(cmd)
    self.assert_success(pants_run)
    self.assertFalse('Lint errors found!' in pants_run.stdout_data)

    # After modifying thrift file
    dir_path = 'contrib/scrooge/tests/thrift/org/pantsbuild/contrib/scrooge/thrift_linter'
    with temporary_file(suffix=".thrift", root_dir=dir_path) as tmp_file:
      tmp_file.write("struct Duck {\n" +
                     "1: optional string quack, \n" +
                     "}\n")
      pants_run = self.run_pants(cmd)
      self.assert_success(pants_run)
      self.assertTrue('Lint errors found!' in pants_run.stdout_data)


  def test_linter_doesnt_run_on_unmodified_thrift(self):
    # thrift-linter doesnt run on un-modified thrift files, by default
    cmd = ['thrift-linter', self.thrift_test_target('all-thrift')]
    pants_run = self.run_pants(cmd)
    self.assert_success(pants_run)
    self.assertFalse('Lint errors found!' in pants_run.stdout_data)
