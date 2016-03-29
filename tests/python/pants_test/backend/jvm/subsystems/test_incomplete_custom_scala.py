# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import contextlib
import os
import random
import re
import shutil
import time

from pants_test.pants_run_integration_test import PantsRunIntegrationTest


class IncompleteCustomScalaIntegrationTest(PantsRunIntegrationTest):
  @contextlib.contextmanager
  def tmp_buildfile(self, path):
    """Temporarily create a BUILD file in the root for custom scala testing"""
    if os.path.exists(self.tmp_build_file_path):
      raise RuntimeError('BUILD file exists failing to avoid overwritting file.'
                         'Ensure that file does not exist from a previous run')
    try:
      shutil.copyfile(path, self.tmp_build_file_path)
      yield
    finally:
      os.remove(self.tmp_build_file_path)

  def pants_run(self, options=None):
    if options is None:
      options = []
    full_options = options + ['clean-all', 'compile', self.target_path]
    return self.run_pants(full_options)

  def setUp(self):
    self.target_path = 'testprojects/src/scala/org/pantsbuild/testproject/scalac/plugin/'
    self.tmp_build_file_path = 'BUILD.CustomScalaIntegTests'

  def test_working_210(self):
    pants_run = self.pants_run(options=['--scala-platform-version=2.10'])
    self.assert_success(pants_run)
    assert re.search('bootstrap-scalastyle_2_10', pants_run.stdout_data), pants_run.stdout_data

  def test_working_211(self):
    pants_run = self.pants_run(options=['--scala-platform-version=2.11'])
    self.assert_success(pants_run)
    assert re.search('bootstrap-scalastyle_2_11', pants_run.stdout_data), pants_run.stdout_data

  def test_working_custom_210(self):
    custom_buildfile = os.path.join(self.target_path, 'custom_210_scalatools.build')
    with self.tmp_buildfile(custom_buildfile):
      pants_run = self.pants_run(
        options=['--scala-platform-version=custom', '--scala-platform-suffix-version=2.10']
      )
      self.assert_success(pants_run)
      assert not re.search('bootstrap-scalastyle_2_10', pants_run.stdout_data)
      assert not re.search('bootstrap-scalastyle_2_11', pants_run.stdout_data)

  def test_working_custom_211(self):
    custom_buildfile = os.path.join(self.target_path, 'custom_211_scalatools.build')
    with self.tmp_buildfile(custom_buildfile):
      pants_run = self.pants_run(
        options=['--scala-platform-version=custom', '--scala-platform-suffix-version=2.11']
      )
      self.assert_success(pants_run)
      assert not re.search('bootstrap-scalastyle_2_10', pants_run.stdout_data)
      assert not re.search('bootstrap-scalastyle_2_11', pants_run.stdout_data)

  def test_missing_compiler(self):
    custom_buildfile = os.path.join(self.target_path, 'custom_211_missing_compiler.build')
    with self.tmp_buildfile(custom_buildfile):
      pants_run = self.pants_run(
        options=['--scala-platform-version=custom', '--scala-platform-suffix-version=2.11']
      )
      self.assert_failure(pants_run)
      assert "Unable to bootstrap tool: 'scalac'" in pants_run.stdout_data

  def test_missing_runtime(self):
    custom_buildfile = os.path.join(self.target_path, 'custom_211_missing_runtime.build')
    with self.tmp_buildfile(custom_buildfile):
      pants_run = self.pants_run(
        options=['--scala-platform-version=custom', '--scala-platform-suffix-version=2.11']
      )
      self.assert_failure(pants_run)
