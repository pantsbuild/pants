# coding=utf-8
# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from pants_test.pants_run_integration_test import PantsRunIntegrationTest


class TestListGoalsIntegration(PantsRunIntegrationTest):
  def test_goals(self):
    command = ['goals']
    pants_run = self.run_pants(command=command)
    self.assert_success(pants_run)
    self.assertIn('to get help for a particular goal', pants_run.stdout_data)
    # Spot check a few core goals.
    self.assertIn('list:', pants_run.stdout_data)
    self.assertIn('test:', pants_run.stdout_data)
    self.assertIn(' fmt:', pants_run.stdout_data)

  def test_ignored_args(self):
    # Test that arguments (some of which used to be relevant) are ignored.
    command = ['goals', '--all', '--graphviz', '--llama']
    pants_run = self.run_pants(command=command)
    self.assert_success(pants_run)
    self.assertIn('to get help for a particular goal', pants_run.stdout_data)
