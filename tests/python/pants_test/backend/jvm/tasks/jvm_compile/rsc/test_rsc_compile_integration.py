# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import os

from pants.util.contextutil import temporary_dir
from pants_test.backend.jvm.tasks.jvm_compile.base_compile_integration_test import BaseCompileIT


class RscCompileIntegration(BaseCompileIT):
  def test_basic_binary(self):
    with temporary_dir() as cache_dir:
      config = {
        'cache.compile.rsc': {'write_to': [cache_dir]},
        'jvm-platform': {'compiler': 'rsc'},
        'compile.rsc': {'execution_strategy': 'subprocess'},
      }

      pants_run = self.run_pants(
        ['compile',
         'testprojects/src/scala/org/pantsbuild/testproject/mutual:bin',
         ],
        config)
      self.assert_success(pants_run)

  def test_basic_binary_hermetic(self):
    with temporary_dir() as cache_dir:
      config = {
        'cache.compile.rsc': {'write_to': [cache_dir]},
        'jvm-platform': {'compiler': 'rsc'},
        'compile.rsc': {
          'execution_strategy': 'hermetic',
          'incremental': False,
        }
      }

      with self.temporary_workdir() as workdir:
        pants_run = self.run_pants_with_workdir(
          ['compile',
           'testprojects/src/scala/org/pantsbuild/testproject/mutual:bin',
           ],
          workdir, config)
        self.assert_success(pants_run)
        path = os.path.join(
          workdir,
          'compile/rsc/current/testprojects.src.scala.org.pantsbuild.testproject.mutual.mutual/current/zinc',
          'classes/org/pantsbuild/testproject/mutual/A.class')
        self.assertTrue(os.path.exists(path))
        path = os.path.join(
          workdir,
          'compile/rsc/current/testprojects.src.scala.org.pantsbuild.testproject.mutual.mutual/current/rsc',
          'm.jar')
        self.assertTrue(os.path.exists(path))
        path = os.path.join(
          workdir,
          'compile/rsc/current/.scala-library-synthetic/current/rsc/index/scala-library-synthetics.jar')
        self.assertTrue(os.path.exists(path))

  def test_executing_multi_target_binary(self):
    with temporary_dir() as cache_dir:
      config = {
        'cache.compile.rsc': {'write_to': [cache_dir]},
        'jvm-platform': {'compiler': 'rsc'},
        'compile.rsc': {'execution_strategy': 'subprocess'}
      }
      with self.temporary_workdir() as workdir:
        pants_run = self.run_pants_with_workdir(
          ['run',
           'examples/src/scala/org/pantsbuild/example/hello/exe',
           ],
          workdir, config)
        self.assert_success(pants_run)
        self.assertIn('Hello, Resource World!', pants_run.stdout_data)

  def test_executing_multi_target_binary_hermetic(self):
    with temporary_dir() as cache_dir:
      config = {
        'cache.compile.rsc': {'write_to': [cache_dir]},
        'jvm-platform': {'compiler': 'rsc'},
        'compile.rsc': {
          'execution_strategy': 'hermetic',
          'incremental': False
        },
        'resolve.ivy': {
          'capture_snapshots': True
        },
      }
      with self.temporary_workdir() as workdir:
        pants_run = self.run_pants_with_workdir(
          ['run',
            'examples/src/scala/org/pantsbuild/example/hello/exe',
          ],
          workdir, config)
        self.assert_success(pants_run)
        self.assertIn('Hello, Resource World!', pants_run.stdout_data)

  def test_rsc_with_abi_debug_default(self):
    with temporary_dir() as cache_dir:
      config = {
        'cache.compile.rsc': {'write_to': [cache_dir]},
        'jvm-platform': {'compiler': 'rsc'},
        'compile.rsc': {
          'execution_strategy': 'hermetic',
          'incremental': False,
          'debug': 'True'
        },
      }
      with self.temporary_workdir() as workdir:
        pants_run = self.run_pants_with_workdir(
          ['compile',
            'testprojects/src/scala/org/pantsbuild/testproject/mutual:bin',
          ],
          workdir, config)
        self.assert_success(pants_run)
        self.assertIn('debug', pants_run.stdout_data)
        self.assertIn('abi', pants_run.stdout_data)
        self.assertIn('211', pants_run.stdout_data)

  def test_rsc_with_abi(self):
    with temporary_dir() as cache_dir:
      config = {
        'cache.compile.rsc': {'write_to': [cache_dir]},
        'jvm-platform': {'compiler': 'rsc'},
        'compile.rsc': {
          'execution_strategy': 'hermetic',
          'incremental': False,
          'abi': '212',
        },
      }
      with self.temporary_workdir() as workdir:
        pants_run = self.run_pants_with_workdir(
          ['compile',
            'testprojects/src/scala/org/pantsbuild/testproject/mutual:bin',
          ],
          workdir, config)
        self.assert_success(pants_run)
        self.assertIn('abi', pants_run.stdout_data)
        self.assertIn('212', pants_run.stdout_data)
