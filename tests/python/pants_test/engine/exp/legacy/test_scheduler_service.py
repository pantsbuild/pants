# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import unittest

import mock

from pants.base.specs import DescendantAddresses
from pants.engine.exp.fs import Path
from pants.engine.exp.legacy.commands import setup_graph
from pants.engine.exp.nodes import FilesystemNode
from pants.pantsd.service.scheduler_service import SchedulerService


class SchedulerServiceTest(unittest.TestCase):
  def setup_scheduler_service(self, *args, **kwargs):
    with setup_graph(*args, **kwargs) as (_, _, scheduler):
      return SchedulerService(scheduler, None, (Path, DescendantAddresses), FilesystemNode)

  def make_setup_args(self, *specs):
    options = mock.Mock()
    options.target_specs = specs
    return dict(options=options)

  def test_invalidate_fsnode(self):
    kwargs = self.make_setup_args('3rdparty/python::')
    scheduler_service = self.setup_scheduler_service(**kwargs)
    initial_node_count = len(scheduler_service)
    self.assertGreater(initial_node_count, 0)
    scheduler_service._handle_batch_event(['3rdparty/python/BUILD'])
    self.assertLess(len(scheduler_service), initial_node_count)

  def test_invalidate_fsnode_incremental(self):
    kwargs = self.make_setup_args('3rdparty/python::')
    scheduler_service = self.setup_scheduler_service(**kwargs)

    node_count = len(scheduler_service)
    self.assertGreater(node_count, 0)

    # Invalidate the '3rdparty/python' Path's DirectoryListing first.
    for filename in ('3rdparty/python/CHANGED_RANDOM_FILE', '3rdparty/python/BUILD'):
      scheduler_service._handle_batch_event([filename])
      node_count, last_node_count = len(scheduler_service), node_count
      self.assertLess(node_count, last_node_count)
