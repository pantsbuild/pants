# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from builtins import object


class PantsDaemonStats(object):
  """Tracks various stats about the daemon."""

  def __init__(self):
    self.target_root_size = 0
    self.affected_targets_size = 0
    self.affected_targets_file_count = 0
    self.scheduler_metrics = {}

  def set_scheduler_metrics(self, scheduler_metrics):
    self.scheduler_metrics = scheduler_metrics

  def set_target_root_size(self, size):
    self.target_root_size = size

  def set_affected_targets_size(self, size):
    self.affected_targets_size = size

  def get_all(self):
    res = dict(self.scheduler_metrics)
    res.update({
      'target_root_size': self.target_root_size,
      'affected_targets_size': self.affected_targets_size,
    })
    return res
