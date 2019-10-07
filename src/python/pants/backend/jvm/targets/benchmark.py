# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.jvm.targets.jvm_target import JvmTarget


class Benchmark(JvmTarget):
  """A caliper benchmark.

  Run it with the ``bench`` goal.
  """
