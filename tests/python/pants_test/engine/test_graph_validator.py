# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import unittest

from pants_test.engine.examples.graph_validator import PartiallyConsumedInputsError
from pants_test.engine.test_scheduler import SchedulerTest


class GraphValidatorSchedulerTest(SchedulerTest, unittest.TestCase):
  def test_no_variant_thrift(self):
    """No `thrift` variant is configured, and so no configuration is selected."""
    build_request = self.request(['compile'], self.no_variant_thrift)

    with self.assertRaises(PartiallyConsumedInputsError):
      self.build_and_walk(build_request)

  def test_unconfigured_thrift(self):
    """The BuildPropertiesPlanner is able to produce a Classpath, but we should still fail.

    A target with ThriftSources doesn't have a thrift config: that input is partially consumed.
    """
    build_request = self.request(['compile'], self.unconfigured_thrift)

    with self.assertRaises(PartiallyConsumedInputsError):
      self.build_and_walk(build_request)
