# coding=utf-8
# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pants_test.pants_run_integration_test import PantsRunIntegrationTest, ensure_engine


class FiledepsIntegrationTest(PantsRunIntegrationTest):

  TARGET = 'examples/src/scala/org/pantsbuild/example/hello/welcome'

  def run_filedeps(self, *filedeps_options):
    args = ['filedeps', self.TARGET]
    args.extend(filedeps_options)

    pants_run = self.run_pants(args)
    self.assert_success(pants_run)
    return pants_run.stdout_data.strip()

  def _get_rel_paths(self, full_paths):
    return {os.path.relpath(full_path, os.getcwd()) for full_path in full_paths}

  @ensure_engine
  def test_filedeps_basic(self):
    expected_output = {
      'examples/src/java/org/pantsbuild/example/hello/greet/BUILD',
      'examples/src/resources/org/pantsbuild/example/hello/world.txt',
      'examples/src/scala/org/pantsbuild/example/hello/welcome/BUILD',
      'examples/src/resources/org/pantsbuild/example/hello/BUILD',
      'examples/src/scala/org/pantsbuild/example/hello/welcome/Welcome.scala',
      'examples/src/java/org/pantsbuild/example/hello/greet/Greeting.java'}
    actual_output = self._get_rel_paths(set(self.run_filedeps().split()))
    self.assertEqual(expected_output, actual_output)

  @ensure_engine
  def test_filedeps_globs(self):
    expected_output = {
      'examples/src/java/org/pantsbuild/example/hello/greet/BUILD',
      'examples/src/scala/org/pantsbuild/example/hello/welcome/BUILD',
      'examples/src/resources/org/pantsbuild/example/hello/world.txt',
      'examples/src/scala/org/pantsbuild/example/hello/welcome/*.scala',
      'examples/src/java/org/pantsbuild/example/hello/greet/*.java',
      'examples/src/resources/org/pantsbuild/example/hello/BUILD'
    }
    actual_output = self._get_rel_paths(set(self.run_filedeps('--filedeps-globs').split()))
    self.assertEqual(expected_output, actual_output)
