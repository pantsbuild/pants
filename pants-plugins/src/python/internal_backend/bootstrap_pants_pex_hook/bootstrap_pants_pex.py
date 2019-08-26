# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import subprocess

from pants.backend.python.targets.python_tests import PythonTests
from pants.build_graph.target import Target
from pants.task.task import Task


class BootstrapPantsPex(Task):

  def execute(self):

    def is_integration_test(target: Target) -> bool:
      return isinstance(target, PythonTests) and "integration" in target.tags

    integration_test_targets = self.context.targets(predicate=is_integration_test)
    if not integration_test_targets:
      return

    subprocess.run(["build-support/bin/bootstrap_pants_pex.sh"], check=True)
