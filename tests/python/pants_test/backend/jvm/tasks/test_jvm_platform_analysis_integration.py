# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
from contextlib import contextmanager
from textwrap import dedent

from pants.util.contextutil import temporary_dir
from pants_test.pants_run_integration_test import PantsRunIntegrationTest


class JvmPlatformAnalysisIntegrationTest(PantsRunIntegrationTest):
  """Make sure jvm-platform-analysis runs properly, especially with respect to caching behavior."""

  class JavaSandbox(object):
    """Testing sandbox for making temporary java_library targets."""

    def __init__(self, test, workdir, javadir):
      self.javadir = javadir
      self.workdir = workdir
      self.test = test
      if not os.path.exists(self.workdir):
        os.makedirs(self.workdir)

    @property
    def build_file_path(self):
      return os.path.join(self.javadir, 'BUILD')

    def write_build_file(self, contents):
      with open(self.build_file_path, 'w') as f:
        f.write(contents)

    def spec(self, name):
      return '{}:{}'.format(self.javadir, name)

    def clean_all(self):
      return self.test.run_pants_with_workdir(['clean-all'], workdir=self.workdir)

    def jvm_platform_validate(self, *targets):
      return self.test.run_pants_with_workdir(['jvm-platform-validate', '--check=fatal']
                                              + map(self.spec, targets),
                                              workdir=self.workdir)

  @contextmanager
  def setup_sandbox(self):
    with temporary_dir('.') as sourcedir:
      with self.temporary_workdir() as workdir:
        javadir = os.path.join(sourcedir, 'src', 'java')
        os.makedirs(javadir)
        yield self.JavaSandbox(self, workdir, javadir)

  @property
  def _good_one_two(self):
    return dedent("""
      java_library(name='one',
        platform='1.7',
      )

      java_library(name='two',
        platform='1.8',
      )
    """)

  @property
  def _bad_one_two(self):
    return dedent("""
      java_library(name='one',
        platform='1.7',
        dependencies=[':two'],
      )

      java_library(name='two',
        platform='1.8',
      )
    """)

  def test_good_targets_works_fresh(self):
    with self.setup_sandbox() as sandbox:
      sandbox.write_build_file(self._good_one_two)
      self.assert_success(sandbox.clean_all())
      self.assert_success(sandbox.jvm_platform_validate('one', 'two'))

  def test_bad_targets_fails_fresh(self):
    with self.setup_sandbox() as sandbox:
      sandbox.write_build_file(self._bad_one_two)
      self.assert_success(sandbox.clean_all())
      self.assert_failure(sandbox.jvm_platform_validate('one', 'two'))

  def test_good_then_bad(self):
    with self.setup_sandbox() as sandbox:
      sandbox.write_build_file(self._good_one_two)
      self.assert_success(sandbox.clean_all())
      self.assert_success(sandbox.jvm_platform_validate('one', 'two'))
      sandbox.write_build_file(self._bad_one_two)
      self.assert_failure(sandbox.jvm_platform_validate('one', 'two'))

  def test_bad_then_good(self):
    with self.setup_sandbox() as sandbox:
      sandbox.write_build_file(self._bad_one_two)
      self.assert_success(sandbox.clean_all())
      self.assert_failure(sandbox.jvm_platform_validate('one', 'two'))
      sandbox.write_build_file(self._good_one_two)
      self.assert_success(sandbox.jvm_platform_validate('one', 'two'))

  def test_good_caching(self):
    # Make sure targets are cached after a good run.
    with self.setup_sandbox() as sandbox:
      sandbox.write_build_file(self._good_one_two)
      self.assert_success(sandbox.clean_all())
      first_run = sandbox.jvm_platform_validate('one', 'two')
      self.assert_success(first_run)
      self.assertIn('Invalidated 2 targets', first_run.stdout_data)
      second_run = sandbox.jvm_platform_validate('one', 'two')
      self.assert_success(second_run)
      self.assertNotIn('Invalidated 2 targets', second_run.stdout_data)

  def test_bad_caching(self):
    # Make sure targets aren't cached after a bad run.
    with self.setup_sandbox() as sandbox:
      sandbox.write_build_file(self._bad_one_two)
      self.assert_success(sandbox.clean_all())
      first_run = sandbox.jvm_platform_validate('one', 'two')
      self.assert_failure(first_run)
      self.assertIn('Invalidated 2 targets', first_run.stdout_data)
      second_run = sandbox.jvm_platform_validate('one', 'two')
      self.assert_failure(second_run)
      self.assertIn('Invalidated 2 targets', second_run.stdout_data)
