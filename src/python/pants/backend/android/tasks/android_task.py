# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from pants.backend.core.tasks.task import Task
from pants.backend.android.distribution.android_distribution import AndroidDistribution

class AndroidTask(Task):

  @classmethod
  def setup_parser(cls, option_group, args, mkflag):
    option_group.add_option(mkflag('sdk-path'), dest='sdk_path', type='string',
                            help='Specify a specific Android SDK to pass to tasks.')

  def __init__(self, context, workdir):
    super(AndroidTask, self).__init__(context, workdir)
    self.forced_sdk = self.context.options.sdk_path or None
    self._android_sdk = None

  @property
  def android_sdk(self):
    if self._android_sdk is None:
      self._android_sdk = AndroidDistribution.cached(self.forced_sdk)
    return self._android_sdk
