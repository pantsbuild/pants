# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import os
from functools import wraps

from pants.backend.jvm.subsystems.resolve_subsystem import JvmResolveSubsystem
from pants.backend.jvm.tasks.jvm_compile.rsc.rsc_compile import RscCompile
from pants.util.contextutil import temporary_dir
from pants_test.backend.jvm.tasks.jvm_compile.base_compile_integration_test import BaseCompileIT


def _for_all_supported_execution_environments(func):
  @wraps(func)
  def wrapper_self(*args, **kwargs):
    for worker_count in [1, 2]:
      for resolver in JvmResolveSubsystem.CHOICES:
        for execution_strategy in RscCompile.ExecutionStrategy.all_variants:
          with temporary_dir() as cache_dir:
            config = {
              'cache.compile.rsc': {'write_to': [cache_dir]},
              'jvm-platform': {'compiler': 'rsc'},
              'compile.rsc': {
                'execution_strategy': execution_strategy.value,
                'worker_count': worker_count,
              },
              'resolver': {
                'resolver': resolver,
              }
            }

            def populate_necessary_hermetic_options():
              config['compile.rsc'].update({
                'incremental': False,
                'use_classpath_jars': False,
              })
              if resolver == 'ivy':
                resolver_scope = 'resolve.ivy'
              else:
                assert resolver == 'coursier'
                resolver_scope = 'resolve.coursier'
              config[resolver_scope] = {
                'capture_snapshots': True,
              }

            execution_strategy.resolve_for_enum_variant({
              'nailgun': lambda: None,
              'subprocess': lambda: None,
              'hermetic': populate_necessary_hermetic_options,
            })()

            func(*args, config=config, **kwargs)
  return wrapper_self


class RscCompileIntegration(BaseCompileIT):

  @_for_all_supported_execution_environments
  def test_basic_binary(self, config):
    with temporary_dir() as temp_dir:
      pants_run = self.run_pants(
        [
          '--pants-distdir={}'.format(temp_dir),
          'binary',
          'testprojects/src/scala/org/pantsbuild/testproject/mutual:bin',
        ],
        config=config,
      )
      self.assert_success(pants_run)
      self.assertIsFile(os.path.join(temp_dir, 'bin.jar'))

  @_for_all_supported_execution_environments
  def test_executing_multi_target_binary(self, config):
    pants_run = self.do_command(
      'run', 'examples/src/scala/org/pantsbuild/example/hello/exe',
      config=config)
    self.assertIn('Hello, Resource World!', pants_run.stdout_data)

  @_for_all_supported_execution_environments
  def test_java_with_transitive_exported_scala_dep(self, config):
    self.do_command(
      'compile', 'testprojects/src/scala/org/pantsbuild/testproject/javadepsonscalatransitive:java-in-different-package',
      config=config)

  @_for_all_supported_execution_environments
  def test_java_sources(self, config):
    self.do_command(
      'compile', 'testprojects/src/scala/org/pantsbuild/testproject/javasources',
      config=config)
