# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import re
from subprocess import PIPE, Popen
from textwrap import dedent
from zipfile import ZipFile

from pants.base.build_environment import get_buildroot
from pants.util.contextutil import temporary_dir
from pants_test.pants_run_integration_test import PantsRunIntegrationTest


class ScopeRuntimeIntegrationTest(PantsRunIntegrationTest):

  @classmethod
  def _spec(cls, name):
    return 'testprojects/src/java/org/pantsbuild/testproject/runtime:{}'.format(name)

  def test_run_runtime_pass(self):
    self.assert_success(self.run_pants([
      '--no-java-strict-deps', 'run', self._spec('runtime-pass'),
    ]))

  def test_run_runtime_fail(self):
    self.assert_failure(self.run_pants([
      '--no-java-strict-deps', 'run', self._spec('runtime-fail'),
    ]))

  def test_compile_compile_pass(self):
    self.assert_success(self.run_pants([
      '--no-java-strict-deps', 'compile', self._spec('compile-pass'),
    ]))

  def test_compile_compile_fail(self):
    self.assert_failure(self.run_pants([
      '--no-java-strict-deps', 'compile', self._spec('compile-fail'),
    ]))

  def test_run_compile_fail(self):
    self.assert_failure(self.run_pants([
      '--no-java-strict-deps', 'run', self._spec('compile-pass'),
    ]))

  def test_runtime_binary_has_correct_contents_and_runs(self):
    with temporary_dir() as distdir:
      run = self.run_pants([
        '--pants-distdir={}'.format(distdir),
        '--no-java-strict-deps',
        'binary',
        self._spec('runtime-pass'),
      ])
      self.assert_success(run)
      binary = os.path.join(distdir, 'runtime-pass.jar')
      self.assertTrue(os.path.exists(binary))
      with ZipFile(binary, 'r') as f:
        self.assertIn('com/google/gson/stream/JsonReader.class', f.namelist())
      p = Popen(['java', '-jar', binary], stdout=PIPE, stderr=PIPE)
      p.communicate()
      self.assertEquals(0, p.returncode)

  def test_compile_binary_has_correct_contents_and_runs(self):
    with temporary_dir() as distdir:
      run = self.run_pants([
        '--pants-distdir={}'.format(distdir),
        '--no-java-strict-deps',
        'binary',
        self._spec('compile-pass'),
      ])
      self.assert_success(run)
      binary = os.path.join(distdir, 'compile-pass.jar')
      self.assertTrue(os.path.exists(binary))
      with ZipFile(binary, 'r') as f:
        self.assertNotIn('com/google/gson/stream/JsonReader.class', f.namelist())
      p = Popen(['java', '-jar', binary], stdout=PIPE, stderr=PIPE)
      p.communicate()
      self.assertNotEquals(0, p.returncode)

  def test_runtime_bundle_contents(self):
    spec = self._spec('runtime-pass')
    with temporary_dir() as distdir:
      with self.pants_results([
        '--pants-distdir={}'.format(distdir),
        '--no-java-strict-deps',
        'bundle',
        spec,
      ]) as run:
        self.assert_success(run)
        bundle_dir = os.path.join(distdir, '{}-bundle'.format(re.sub(r'[:/]', '.', spec)))
        binary = os.path.join(bundle_dir, 'runtime-pass.jar')
        self.assertTrue(os.path.exists(binary))
        self.assertTrue(any(name.startswith('3rdparty.gson')
                            for name in os.listdir(os.path.join(bundle_dir, 'libs'))))

  def test_compile_bundle_contents(self):
    spec = self._spec('compile-pass')
    with temporary_dir() as distdir:
      with self.pants_results([
        '--pants-distdir={}'.format(distdir),
        '--no-java-strict-deps',
        'bundle',
        spec,
      ]) as run:
        self.assert_success(run)
        bundle_dir = os.path.join(distdir, '{}-bundle'.format(re.sub(r'[:/]', '.', spec)))
        binary = os.path.join(bundle_dir, 'compile-pass.jar')
        self.assertTrue(os.path.exists(binary))
        self.assertFalse(any(name.startswith('3rdparty.gson')
                             for name in os.listdir(os.path.join(bundle_dir, 'libs'))))


class ScopeChangesCacheInvalidationIntegrationTest(PantsRunIntegrationTest):

  def test_invalidate_compiles_when_scopes_change(self):
    with temporary_dir(root_dir=get_buildroot()) as workdir_parent:
      workdir = os.path.join(workdir_parent, '.pants.d')
      os.makedirs(workdir)
      with temporary_dir(root_dir=get_buildroot()) as tmp_project:
        with open(os.path.join(tmp_project, 'Foo.java'), 'w') as f:
          f.write('public class Foo {}')
        with open(os.path.join(tmp_project, 'Bar.java'), 'w') as f:
          f.write('public class Bar extends Foo {}')

        def spec(name):
          return '{}:{}'.format(os.path.basename(tmp_project), name)

        def write_build(scope):
          with open(os.path.join(tmp_project, 'BUILD'), 'w') as f:
            f.write(dedent('''
              java_library(name='foo',
                sources=['Foo.java'],
              )
              java_library(name='bar',
                sources=['Bar.java'],
                dependencies=[
                  scoped(scope='{scope}', address=':foo'),
                ],
              )
              jvm_binary(name='bin',
                main='Foo',
                dependencies=[':foo'],
              )
            ''').strip().format(scope=scope))

        write_build('')
        self.assert_success(self.run_pants_with_workdir([
          '--no-java-strict-deps', 'compile', spec('bar'),
        ], workdir=workdir), msg='Normal build from a clean cache failed. Something may be wrong '
                                 'with the test setup.')

        write_build('runtime')
        self.assert_failure(self.run_pants_with_workdir([
          '--no-java-strict-deps', 'compile', spec('bar'),
        ], workdir=workdir), msg='Build from a dirty cache with the dependency on :foo scoped to '
                                 'runtime passed, when it should have had a compile failure. The '
                                 'cache may not have been invalidated.')

        write_build('compile')
        self.assert_success(self.run_pants_with_workdir([
          '--no-java-strict-deps', 'compile', spec('bar'),
        ], workdir=workdir), msg='Build from a dirty cache with the scope changed to compile '
                                 'failed. The cache may not have been invalidated.')

        write_build('compile')
        self.assert_failure(self.run_pants_with_workdir([
          '--no-java-strict-deps', 'run', spec('bin'),
        ], workdir=workdir), msg='Attempt to run binary with the dependency on :foo scoped to '
                                 'compile passed. This should have caused a runtime failure.')
