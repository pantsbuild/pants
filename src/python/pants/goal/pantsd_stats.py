# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)


class PantsDaemonStats(object):
  """Tracks various stats about the daemon."""

  def __init__(self):
    self.preceding_graph_size = None
    self.target_root_size = 0
    self.affected_targets_size = 0
    self.affected_targets_file_count = 0
    self.resulting_graph_size = None
    self.scheduler_metrics = {}

  def set_scheduler_metrics(self, scheduler_metrics):
    self.scheduler_metrics = scheduler_metrics

  def set_preceding_graph_size(self, size):
    self.preceding_graph_size = size

  def set_target_root_size(self, size):
    self.target_root_size = size

  def set_affected_targets_size(self, size):
    self.affected_targets_size = size

  def set_resulting_graph_size(self, size):
    self.resulting_graph_size = size

  def get_all(self):
    res = dict(self.scheduler_metrics)
    res.update({
      'preceding_graph_size': self.preceding_graph_size,
      'target_root_size': self.target_root_size,
      'affected_targets_size': self.affected_targets_size,
      'resulting_graph_size': self.resulting_graph_size,
    })
    return res
