# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)


class PantsDaemonStats(object):
  """Tracks various stats about the daemon."""

  def __init__(self):
    self.resident_graph_size = None
    self.resulting_graph_size = None

  def set_resident_graph_size(self, size):
    self.resident_graph_size = size

  def set_resulting_graph_size(self, size):
    self.resulting_graph_size = size

  def get_all(self):
    return {
      'resident_graph_size': self.resident_graph_size,
      'resulting_graph_size': self.resulting_graph_size,
    }
