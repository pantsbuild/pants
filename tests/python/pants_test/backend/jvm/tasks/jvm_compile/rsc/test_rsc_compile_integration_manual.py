# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os

from pants.java.distribution.distribution import DistributionLocator
from pants_test.backend.jvm.tasks.jvm_compile.base_compile_integration_test import BaseCompileIT
from pants_test.subsystem.subsystem_util import init_subsystem


class RscCompileIntegrationManual(BaseCompileIT):

  def test_rsc_hermetic_jvm_options(self):
    # Remove all the symlinks under jdk in travis: https://github.com/pantsbuild/pants/issues/8460
    # Otherwise globbing from jdk home would error out.
    jdk_home = DistributionLocator.global_instance().cached().home
    if os.path.exists(jdk_home):
      init_subsystem(DistributionLocator)
      symlinks = [f for f in os.listdir(jdk_home) if os.path.islink(f)]
      for s in symlinks:
        os.remove(s)

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
