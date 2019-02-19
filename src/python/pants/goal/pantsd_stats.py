# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from builtins import object


class PantsDaemonStats(object):
  """Tracks various stats about the daemon."""

  def __init__(self):
    self.scheduler_metrics = {}

  def set_scheduler_metrics(self, scheduler_metrics):
    self.scheduler_metrics = scheduler_metrics

  def set_target_root_size(self, size):
    self.scheduler_metrics['target_root_size'] = size

  def set_affected_targets_size(self, size):
    self.scheduler_metrics['affected_targets_size'] = size

  def get_all(self):
    for key in ['target_root_size', 'affected_targets_size']:
      self.scheduler_metrics.setdefault(key, 0)
    return self.scheduler_metrics
