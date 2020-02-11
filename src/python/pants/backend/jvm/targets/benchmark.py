# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.jvm.targets.jvm_target import JvmTarget
from pants.backend.jvm.targets.runtime_platform_mixin import RuntimePlatformMixin
from pants.base.payload import Payload


class Benchmark(JvmTarget, RuntimePlatformMixin):
  """A caliper benchmark.

  Run it with the ``bench`` goal.
  """

  def __init__(self, payload=None, runtime_platform=None, **kwargs):
    """
    :param str runtime_platform: The name of the platform (defined under the jvm-platform subsystem) to use
                         for runtime (that is, a key into the --jvm-platform-platforms
                         dictionary). If unspecified, the platform will default to the first one of
                         these that exist: (1) the default_runtime_platform specified for
                         jvm-platform, (2) the platform that would be used for the platform kwarg.
    """
    payload = payload or Payload()
    self.init_runtime_platform(payload, runtime_platform)
    super().__init__(payload=payload, **kwargs)
