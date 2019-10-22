# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os

from pants.backend.jvm.tasks.jvm_compile.rsc.rsc_compile import RscCompile
from pants.util.contextutil import environment_as
from pants_test.backend.jvm.tasks.jvm_compile.base_compile_integration_test import BaseCompileIT


def ensure_compile_rsc_execution_strategy(workflow):
  """A decorator for running an integration test with ivy and coursier as the resolver."""

  def decorator(f):
    def wrapper(self, *args, **kwargs):
      for strategy in RscCompile.ExecutionStrategy.all_values():
        with environment_as(
          HERMETIC_ENV='PANTS_COMPILE_RSC_EXECUTION_STRATEGY',
          PANTS_COMPILE_RSC_EXECUTION_STRATEGY=strategy.value,
          PANTS_COMPILE_RSC_WORKFLOW=workflow.value,
          PANTS_CACHE_COMPILE_RSC_IGNORE='True'):
          f(self, *args, **kwargs)

    return wrapper
  return  decorator


class RscCompileIntegration(BaseCompileIT):

  rsc_and_zinc = RscCompile.JvmCompileWorkflowType.rsc_and_zinc
  outline_and_zinc = RscCompile.JvmCompileWorkflowType.outline_and_zinc

  @ensure_compile_rsc_execution_strategy(outline_and_zinc)
  @ensure_compile_rsc_execution_strategy(rsc_and_zinc)
  def test_basic_binary(self):
    with self.do_command_yielding_workdir('compile', 'testprojects/src/scala/org/pantsbuild/testproject/mutual:bin') as pants_run:
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

  @ensure_compile_rsc_execution_strategy(rsc_and_zinc)
  def test_executing_multi_target_binary(self):
    pants_run = self.do_command('run', 'examples/src/scala/org/pantsbuild/example/hello/exe')
    self.assertIn('Hello, Resource World!', pants_run.stdout_data)

  @ensure_compile_rsc_execution_strategy(rsc_and_zinc)
  def test_java_with_transitive_exported_scala_dep(self):
    self.do_command('compile', 'testprojects/src/scala/org/pantsbuild/testproject/javadepsonscalatransitive:java-in-different-package')

  @ensure_compile_rsc_execution_strategy(rsc_and_zinc)
  def test_java_sources(self):
    self.do_command('compile', 'testprojects/src/scala/org/pantsbuild/testproject/javasources')

  @ensure_compile_rsc_execution_strategy
  def test_node_dependencies(self):
    self.do_command('compile', 'contrib/node/examples/src/java/org/pantsbuild/testproject/jsresources')

  def test_rsc_hermetic_jvm_options(self):
    self._test_hermetic_jvm_options(self.rsc_and_zinc)

  def test_youtline_hermetic_jvm_options(self):
    self._test_hermetic_jvm_options(self.outline_and_zinc)

  def _test_hermetic_jvm_options(self, workflow):
    pants_run = self.run_pants(['compile', 'examples/src/scala/org/pantsbuild/example/hello/exe'],
      config={
        'cache.compile.rsc': {'ignore': True},
        'jvm-platform': {'compiler': 'rsc'},
        'compile.rsc': {
          'workflow': workflow.value,
          'execution_strategy': 'hermetic',
        },
        'rsc': {
          'jvm_options': [
            '-Djava.security.manager=java.util.Optional'
          ]
        }
      })
    self.assert_failure(pants_run)
    self.assertIn(
      'Could not create SecurityManager: java.util.Optional',
      pants_run.stdout_data,
      'Pants run is expected to fail and contain error about loading an invalid security '
      'manager class, but it did not.')
