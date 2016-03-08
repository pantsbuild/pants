# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.task.task import Task

from pants.contrib.android.distribution.android_distribution import AndroidDistribution


class AndroidTask(Task):
  """Base class for Android tasks that may require the Android SDK."""

  @classmethod
  def register_options(cls, register):
    super(AndroidTask, cls).register_options(register)
    register('--sdk-path', help='Use the Android SDK at this path.')

  def __init__(self, *args, **kwargs):
    super(AndroidTask, self).__init__(*args, **kwargs)
    self._sdk_path = self.get_options().sdk_path or None

  @property
  def android_sdk(self):
    """Instantiate an Android SDK distribution that provides tools to android tasks."""
    return AndroidDistribution.cached(self._sdk_path)
