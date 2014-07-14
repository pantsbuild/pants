# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from pants.backend.core.tasks.task import Task
from pants.base.exceptions import TaskError
from pants.backend.android.distribution.android_distribution import AndroidDistribution

class AndroidTask(Task):

  def __init__(self, context, workdir):
    super(AndroidTask, self).__init__(context, workdir)
    try:
      self._dist = AndroidDistribution.cached()
    except AndroidDistribution.Error as e:
      raise TaskError(e)
