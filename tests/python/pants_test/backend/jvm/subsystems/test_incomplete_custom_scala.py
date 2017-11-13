# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import contextlib
import os
import re
import shutil
from textwrap import dedent

from pants.base.build_environment import get_buildroot
from pants.util.contextutil import temporary_dir
from pants.util.dirutil import safe_file_dump
from pants_test.pants_run_integration_test import PantsRunIntegrationTest


class IncompleteCustomScalaIntegrationTest(PantsRunIntegrationTest):
  @contextlib.contextmanager
  def tmp_custom_scala(self, path_suffix):
    """Temporarily create a BUILD file in the root for custom scala testing."""
    if os.path.exists(self.tmp_build_file_path):
      raise RuntimeError('BUILD file exists failing to avoid overwritting file.'
                         'Ensure that file does not exist from a previous run')
    path = os.path.join(self.target_path, path_suffix)
    try:
      # Bootstrap the BUILD file.
      shutil.copyfile(path, self.tmp_build_file_path)
      # And create an empty scalastyle config.
      with self.tmp_scalastyle_config() as scalastyle_config_option:
        yield scalastyle_config_option
    finally:
      os.remove(self.tmp_build_file_path)

  @contextlib.contextmanager
  def tmp_scalastyle_config(self):
    with temporary_dir(root_dir=get_buildroot()) as scalastyle_dir:
      path = os.path.join(scalastyle_dir, 'config.xml')
      safe_file_dump(path, '''<scalastyle/>''')
      yield '--lint-scalastyle-config={}'.format(path)

  def pants_run(self, options=None):
    if options is None:
      options = []
    full_options = options + ['clean-all', 'compile', 'lint', self.target_path]
    return self.run_pants(full_options)

  def run_repl(self, target, program, options=None):
    """Run a repl for the given target with the given input, and return stdout_data."""
    command = ['repl']
    if options:
      command.extend(options)
    command.extend([target, '--quiet'])
    return self.run_pants(command=command, stdin_data=program)

  @classmethod
  def hermetic(cls):
    return True

  def setUp(self):
    self.target_path = 'testprojects/src/scala/org/pantsbuild/testproject/custom_scala_platform'
    self.tmp_build_file_path = 'BUILD.CustomScalaIntegTests'

  def test_working_210(self):
    with self.tmp_scalastyle_config() as scalastyle_config_option:
      pants_run = self.pants_run(options=['--scala-platform-version=2.10', scalastyle_config_option])
      self.assert_success(pants_run)
      assert re.search('bootstrap-scalastyle_2_10', pants_run.stdout_data), pants_run.stdout_data

  def test_working_211(self):
    with self.tmp_scalastyle_config() as scalastyle_config_option:
      pants_run = self.pants_run(options=['--scala-platform-version=2.11', scalastyle_config_option])
      self.assert_success(pants_run)
      assert re.search('bootstrap-scalastyle_2_11', pants_run.stdout_data), pants_run.stdout_data

  def test_working_212(self):
    with self.tmp_scalastyle_config() as scalastyle_config_option:
      pants_run = self.pants_run(options=['--scala-platform-version=2.12', scalastyle_config_option])
      self.assert_success(pants_run)
      assert re.search('bootstrap-scalastyle_2_12', pants_run.stdout_data), pants_run.stdout_data

  def test_working_custom_210(self):
    with self.tmp_custom_scala('custom_210_scalatools.build') as scalastyle_config_option:
      pants_run = self.pants_run(
        options=[
          '--scala-platform-version=custom',
          '--scala-platform-suffix-version=2.10',
          scalastyle_config_option,
        ]
      )
      self.assert_success(pants_run)
      assert not re.search('bootstrap-scalastyle_2_10', pants_run.stdout_data)
      assert not re.search('bootstrap-scalastyle_2_11', pants_run.stdout_data)

  def test_repl_working_custom_210(self):
    with self.tmp_custom_scala('custom_210_scalatools.build') as scalastyle_config_option:
      pants_run = self.run_repl(
        'testprojects/src/scala/org/pantsbuild/testproject/custom_scala_platform',
        dedent("""
            import org.pantsbuild.testproject.custom_scala_platform
            Hello.main(Seq("World").toArray))
          """),
        options=[
          '--scala-platform-version=custom',
          '--scala-platform-suffix-version=2.10',
          scalastyle_config_option,
        ]
      )

      # Make sure this didn't happen:
      # FAILURE: No bootstrap callback registered for //:scala-repl in scala-platform
      self.assert_success(pants_run)

  def test_repl_working_custom_211(self):
    with self.tmp_custom_scala('custom_211_scalatools.build') as scalastyle_config_option:
      pants_run = self.run_repl(
        'testprojects/src/scala/org/pantsbuild/testproject/custom_scala_platform',
        dedent("""
            import org.pantsbuild.testproject.custom_scala_platform
            Hello.main(Seq("World").toArray))
          """),
        options=[
          '--scala-platform-version=custom',
          '--scala-platform-suffix-version=2.10',
          scalastyle_config_option,
        ]
      )

      # Make sure this didn't happen:
      # FAILURE: No bootstrap callback registered for //:scala-repl in scala-platform
      self.assert_success(pants_run)

  def test_working_custom_211(self):
    with self.tmp_custom_scala('custom_211_scalatools.build') as scalastyle_config_option:
      pants_run = self.pants_run(
        options=[
          '--scala-platform-version=custom',
          '--scala-platform-suffix-version=2.11',
          scalastyle_config_option,
        ]
      )
      self.assert_success(pants_run)
      assert not re.search('bootstrap-scalastyle_2_10', pants_run.stdout_data)
      assert not re.search('bootstrap-scalastyle_2_11', pants_run.stdout_data)

  def test_missing_compiler(self):
    with self.tmp_custom_scala('custom_211_missing_compiler.build') as scalastyle_config_option:
      pants_run = self.pants_run(
        options=[
          '--scala-platform-version=custom',
          '--scala-platform-suffix-version=2.11',
          scalastyle_config_option,
        ]
      )
      self.assert_failure(pants_run)
      assert "Unable to bootstrap tool: 'scalac'" in pants_run.stdout_data

  def test_missing_runtime(self):
    with self.tmp_custom_scala('custom_211_missing_runtime.build') as scalastyle_config_option:
      pants_run = self.pants_run(
        options=[
          '--scala-platform-version=custom',
          '--scala-platform-suffix-version=2.11',
          scalastyle_config_option,
        ]
      )
      self.assert_failure(pants_run)
