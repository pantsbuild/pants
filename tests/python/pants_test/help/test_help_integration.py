# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants_test.pants_run_integration_test import PantsRunIntegrationTest


class TestHelpIntegration(PantsRunIntegrationTest):

  def test_help(self):
    command = ['help']
    pants_run = self.run_pants(command=command)
    self.assert_success(pants_run)
    self.assertIn('Usage:', pants_run.stdout_data)
    # spot check to see that a public global option is printed
    self.assertIn('--level', pants_run.stdout_data)
    self.assertIn('Global options:', pants_run.stdout_data)

  def test_help_advanced(self):
    command = ['help-advanced']
    pants_run = self.run_pants(command=command)
    self.assert_success(pants_run)
    self.assertIn('Global advanced options:', pants_run.stdout_data)
    # Spot check to see that a global advanced option is printed
    self.assertIn('--pants-bootstrapdir', pants_run.stdout_data)

  def test_help_all(self):
    command = ['help-all']
    pants_run = self.run_pants(command=command)
    self.assert_success(pants_run)
    # Spot check to see that scope headings are printed
    self.assertIn('test.junit options:', pants_run.stdout_data)
    # Spot check to see that full args for all options are printed
    self.assertIn('--binary-dup-max-dups', pants_run.stdout_data)
    # Spot check to see that subsystem options are printing
    self.assertIn('--jvm-options', pants_run.stdout_data)

  def test_help_all_advanced(self):
    command = ['--help-all', '--help-advanced']
    pants_run = self.run_pants(command=command)
    self.assert_success(pants_run)
    # Spot check to see that scope headings are printed even for advanced options
    self.assertIn('test.junit options:', pants_run.stdout_data)
    self.assertIn('cache.test.junit advanced options:', pants_run.stdout_data)
    # Spot check to see that full args for all options are printed
    self.assertIn('--binary-dup-max-dups', pants_run.stdout_data)
    self.assertIn('--cache-test-junit-read', pants_run.stdout_data)
    # Spot check to see that subsystem options are printing
    self.assertIn('--jvm-options', pants_run.stdout_data)
    # Spot check to see that advanced subsystem options are printing
    self.assertIn('--jvm-max-subprocess-args', pants_run.stdout_data)
