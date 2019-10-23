# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.jvm.tasks.jvm_compile.rsc.rsc_compile import RscCompile
from pants.util.contextutil import environment_as
from pants_test.backend.jvm.tasks.jvm_compile.base_compile_integration_test import BaseCompileIT


def ensure_compile_rsc_execution_strategy(workflow, **env_kwargs):
  """A decorator for running an integration test with ivy and coursier as the resolver."""

  def decorator(f):
    def wrapper(self, *args, **kwargs):
      for strategy in RscCompile.ExecutionStrategy.all_values():
        with environment_as(
          HERMETIC_ENV='PANTS_COMPILE_RSC_EXECUTION_STRATEGY',
          PANTS_COMPILE_RSC_EXECUTION_STRATEGY=strategy.value,
          PANTS_COMPILE_RSC_WORKFLOW=workflow.value,
          PANTS_CACHE_COMPILE_RSC_IGNORE='True',
          **env_kwargs):
          f(self, *args, **kwargs)

    return wrapper
  return decorator
  

class RscCompileIntegrationBase(BaseCompileIT):

  rsc_and_zinc = RscCompile.JvmCompileWorkflowType.rsc_and_zinc
  outline_and_zinc = RscCompile.JvmCompileWorkflowType.outline_and_zinc

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
