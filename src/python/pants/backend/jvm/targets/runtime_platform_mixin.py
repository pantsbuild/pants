# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from abc import ABC

from pants.backend.jvm.subsystems.jvm_platform import JvmPlatform
from pants.base.payload_field import PrimitiveField


class RuntimePlatformMixin(ABC):
  """A mixin that identifies a target class as one that can have a jvm runtime_platform.

  mixin in usage

  change __init__:
    - Add runtime_platform=None to the kwargs.
    - Add the following to the doc string:
    :param str runtime_platform: The name of the platform (defined under the jvm-platform subsystem)
      to use for runtime (that is, a key into the --jvm-platform-platforms dictionary). If
      unspecified, the platform will default to the first one of these that exist: (1) the
      default_runtime_platform specified for jvm-platform, (2) the platform that would be used for
      the platform kwarg.

  :API: public
  """

  def init_runtime_platform(self, payload, runtime_platform):
    payload.add_fields({
      'runtime_platform': PrimitiveField(runtime_platform),
    })

  @property
  def runtime_platform(self):
    """Runtime platform associated with this target.

    :return: The jvm platform object.
    :rtype: JvmPlatformSettings
    """
    return JvmPlatform.global_instance().get_runtime_platform_for_target(self)
