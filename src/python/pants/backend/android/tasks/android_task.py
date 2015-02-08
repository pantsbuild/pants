# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.backend.android.distribution.android_distribution import AndroidDistribution
from pants.backend.core.tasks.task import Task


class AndroidTask(Task):
  """Base class for Android tasks that may require the Android SDK."""

  @classmethod
  def register_options(cls, register):
    super(AndroidTask, cls).register_options(register)
    register('--sdk-path', help='Use the Android SDK at this path.')

  def __init__(self, *args, **kwargs):
    super(AndroidTask, self).__init__(*args, **kwargs)
    self.forced_sdk = self.get_options().sdk_path or None
    self._android_sdk = None

  @property
  def android_sdk(self):
    if self._android_sdk is None:
      self._android_sdk = AndroidDistribution.cached(self.forced_sdk)
    return self._android_sdk
