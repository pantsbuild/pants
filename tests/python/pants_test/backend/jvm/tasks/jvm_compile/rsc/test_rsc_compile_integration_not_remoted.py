# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants_test.backend.jvm.tasks.jvm_compile.base_compile_integration_test import BaseCompileIT


class RscCompileIntegrationNotRemoted(BaseCompileIT):

  def test_rsc_hermetic_jvm_options(self):
    pants_run = self.run_pants(['compile', 'examples/src/scala/org/pantsbuild/example/hello/exe'],
      config={
        'cache.compile.rsc': {'ignore': True},
        'jvm-platform': {'compiler': 'rsc'},
        'compile.rsc': {
          'workflow': 'rsc-and-zinc',
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
