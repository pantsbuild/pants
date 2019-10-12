# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os

from pants.backend.jvm.subsystems.resolve_subsystem import JvmResolveSubsystem
from pants.backend.jvm.tasks.jvm_compile.rsc.rsc_compile import RscCompile
from pants.util.contextutil import temporary_dir
from pants_test.backend.jvm.tasks.jvm_compile.base_compile_integration_test import BaseCompileIT
from pants_test.test_base import AbstractTestGenerator


def _for_all_supported_execution_environments(func):
  func._with_run_config = True
  return func


class RscCompileIntegration(BaseCompileIT, AbstractTestGenerator):

  @classmethod
  def generate_tests(cls):
    tests_with_generated_config = {
      name: func for name, func in cls.__dict__.items() if getattr(func, '_with_run_config', False)
    }

    for worker_count in [1, 2]:
      for resolver in JvmResolveSubsystem.CHOICES:
        for execution_strategy in RscCompile.ExecutionStrategy.all_values():
          with temporary_dir() as cache_dir:
            config = {
              'cache.compile.rsc': {'write_to': [cache_dir]},
              'jvm-platform': {'compiler': 'rsc'},
              'compile.rsc': {
                'workflow': 'rsc-and-zinc',
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

            execution_strategy.resolve_for_enum_variant({
              'nailgun': lambda: None,
              'subprocess': lambda: None,
              'hermetic': populate_necessary_hermetic_options,
            })()

            for name, test in tests_with_generated_config.items():
              cls.add_test(
                'test_{}_resolver_{}_strategy_{}_worker_{}'
                .format(name, resolver, execution_strategy.value, worker_count),
                lambda this: test(this, config=config.copy()))

  @_for_all_supported_execution_environments
  def basic_binary(self, config):
    with self.do_command_yielding_workdir(
        'compile', 'testprojects/src/scala/org/pantsbuild/testproject/mutual:bin',
        config=config) as pants_run:
      zinc_compiled_classfile = os.path.join(
        pants_run.workdir,
        'compile/rsc/current/testprojects.src.scala.org.pantsbuild.testproject.mutual.mutual/current/zinc',
        'classes/org/pantsbuild/testproject/mutual/A.class')
      self.assert_is_file(zinc_compiled_classfile)
      rsc_header_jar = os.path.join(
        pants_run.workdir,
        'compile/rsc/current/testprojects.src.scala.org.pantsbuild.testproject.mutual.mutual/current/rsc',
        'm.jar')
      self.assert_is_file(rsc_header_jar)

  @_for_all_supported_execution_environments
  def executing_multi_target_binary(self, config):
    pants_run = self.do_command(
      'run', 'examples/src/scala/org/pantsbuild/example/hello/exe',
      config=config)
    self.assertIn('Hello, Resource World!', pants_run.stdout_data)

  @_for_all_supported_execution_environments
  def java_with_transitive_exported_scala_dep(self, config):
    self.do_command(
      'compile', 'testprojects/src/scala/org/pantsbuild/testproject/javadepsonscalatransitive:java-in-different-package',
      config=config)

  @_for_all_supported_execution_environments
  def java_sources(self, config):
    self.do_command(
      'compile', 'testprojects/src/scala/org/pantsbuild/testproject/javasources',
      config=config)


RscCompileIntegration.generate_tests()
