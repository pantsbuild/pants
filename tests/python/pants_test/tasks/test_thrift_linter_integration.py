# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from pants_test.pants_run_integration_test import PantsRunIntegrationTest

class ThriftLinterTest(PantsRunIntegrationTest):
  def assertSuccess(self, pants_run):
    self.assertEquals(pants_run.returncode, self.PANTS_SUCCESS_CODE)

  def assertFailure(self, pants_run):
    self.assertNotEquals(pants_run.returncode, self.PANTS_SUCCESS_CODE)

  def test_good(self):
    # thrift-linter should pass without warnings with correct thrift files.
    cmd = ['goal',
           'thrift-linter',
           'testprojects/src/thrift/com/pants/thrift_linter:good-thrift']
    pants_run = self.run_pants(cmd)
    self.assertSuccess(pants_run)
    self.assertFalse('Lint errors found!' in pants_run.stdout_data)

  def test_bad_default(self):
    # thrift-linter fails on linter errors.
    cmd = ['goal',
           'thrift-linter',
           'testprojects/src/thrift/com/pants/thrift_linter:bad-thrift-default']
    pants_run = self.run_pants(cmd)
    self.assertSuccess(pants_run)
    self.assertTrue('Lint errors found!' in pants_run.stdout_data)

  def test_bad_strict(self):
    # thrift-linter fails on linter errors (BUILD target defines thrift_linter_strict=True)
    cmd = ['goal',
           'thrift-linter',
           'testprojects/src/thrift/com/pants/thrift_linter:bad-thrift-strict']
    pants_run = self.run_pants(cmd)
    self.assertFailure(pants_run)
    self.assertTrue('Lint errors found!' in pants_run.stdout_data)

  def test_bad_non_strict(self):
    # thrift-linter fails on linter errors (BUILD target defines thrift_linter_strict=False)
    cmd = ['goal',
           'thrift-linter',
           'testprojects/src/thrift/com/pants/thrift_linter:bad-thrift-non-strict']
    pants_run = self.run_pants(cmd)
    self.assertSuccess(pants_run)
    self.assertTrue('Lint errors found!' in pants_run.stdout_data)

  def test_bad_default_override(self):
    # thrift-linter fails with command line flag overriding the BUILD section.
    cmd = ['goal',
           'thrift-linter',
           'testprojects/src/thrift/com/pants/thrift_linter:bad-thrift-default',
           '--thrift-linter-strict']
    pants_run = self.run_pants(cmd)
    self.assertFailure(pants_run)
    self.assertTrue('Lint errors found!' in pants_run.stdout_data)

  def test_bad_strict_override(self):
    # thrift-linter passes with non-strict command line flag overriding the BUILD section.
    cmd = ['goal',
           'thrift-linter',
           'testprojects/src/thrift/com/pants/thrift_linter:bad-thrift-strict',
           '--no-thrift-linter-strict']
    pants_run = self.run_pants(cmd)
    self.assertSuccess(pants_run)
    self.assertTrue('Lint errors found!' in pants_run.stdout_data)

  def test_bad_non_strict_override(self):
    # thrift-linter fails with command line flag overriding the BUILD section.
    cmd = ['goal',
           'thrift-linter',
           'testprojects/src/thrift/com/pants/thrift_linter:bad-thrift-non-strict',
           '--thrift-linter-strict']
    pants_run = self.run_pants(cmd)
    self.assertFailure(pants_run)
    self.assertTrue('Lint errors found!' in pants_run.stdout_data)

  def test_bad_pants_ini_strict(self):
    # thrift-linter fails if pants.ini has a thrift-linter:strict=True setting
    cmd = ['goal',
           'thrift-linter',
           'testprojects/src/thrift/com/pants/thrift_linter:bad-thrift-default',]
    pants_ini_config = {'thrift-linter': {'strict': True}}
    pants_run = self.run_pants(cmd, config = pants_ini_config)
    self.assertFailure(pants_run)
    self.assertTrue('Lint errors found!' in pants_run.stdout_data)

  def test_bad_pants_ini_strict_overridden(self):
    # thrift-linter passes if pants.ini has a thrift-linter:strict=True setting and
    # a command line non-strict flag is passed.
    cmd = ['goal',
           'thrift-linter',
           'testprojects/src/thrift/com/pants/thrift_linter:bad-thrift-default',
           '--no-thrift-linter-strict']
    pants_ini_config = {'thrift-linter': {'strict': True}}
    pants_run = self.run_pants(cmd, config = pants_ini_config)
    self.assertSuccess(pants_run)
    self.assertTrue('Lint errors found!' in pants_run.stdout_data)
