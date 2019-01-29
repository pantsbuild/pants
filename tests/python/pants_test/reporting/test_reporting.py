# coding=utf-8
# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from pants.goal.run_tracker import RunTracker
from pants.reporting.reporting import Reporting
from pants_test.test_base import TestBase


class ReportingTest(TestBase):

  # Options for Zipkin tracing
  trace_id = "0123456789abcdef"
  parent_id = "123456789abcdef0"
  zipkin_endpoint = 'http://localhost:9411/api/v1/spans'

  def test_raise_no_zipkin_endpoint_set(self):

    options = {'reporting': {'zipkin_trace_id': self.trace_id, 'zipkin_parent_id': self.parent_id}}
    context = self.context(for_subsystems=[RunTracker, Reporting], options=options)
    run_tracker = RunTracker.global_instance()
    reporting = Reporting.global_instance()

    with self.assertRaises(ValueError) as result:
      reporting.initialize(run_tracker, context.options)

    self.assertTrue(
      "The zipkin_endpoint flag must be set if trace_id and parent_id are given." in str(result.exception)
    )

  def test_raise_no_parent_id_set(self):

    options = {'reporting': {'zipkin_trace_id': self.trace_id, 'zipkin_endpoint': self.zipkin_endpoint}}
    context = self.context(for_subsystems=[RunTracker, Reporting], options=options)

    run_tracker = RunTracker.global_instance()
    reporting = Reporting.global_instance()

    with self.assertRaises(ValueError) as result:
      reporting.initialize(run_tracker, context.options)

    self.assertTrue(
      "Flags trace_id and parent_id must both either be set or not set." in str(result.exception)
    )

  def test_raise_no_trace_id_set(self):

    options = {'reporting': {'zipkin_parent_id': self.parent_id, 'zipkin_endpoint': self.zipkin_endpoint}}
    context = self.context(for_subsystems=[RunTracker, Reporting], options=options)

    run_tracker = RunTracker.global_instance()
    reporting = Reporting.global_instance()

    with self.assertRaises(ValueError) as result:
      reporting.initialize(run_tracker, context.options)

    self.assertTrue(
      "Flags trace_id and parent_id must both either be set or not set." in str(result.exception)
    )

  def test_raise_no_trace_id_and_zipkin_endpoint_set(self):

    options = {'reporting': {'zipkin_parent_id': self.parent_id}}
    context = self.context(for_subsystems=[RunTracker, Reporting], options=options)

    run_tracker = RunTracker.global_instance()
    reporting = Reporting.global_instance()

    with self.assertRaises(ValueError) as result:
      reporting.initialize(run_tracker, context.options)

    self.assertTrue(
      "Flags trace_id and zipkin_endpoint must be set if parent_id is given." in str(result.exception)
    )

  def test_raise_no_parent_id_and_zipkin_endpoint_set(self):

    options = {'reporting': {'zipkin_trace_id': self.trace_id}}
    context = self.context(for_subsystems=[RunTracker, Reporting], options=options)

    run_tracker = RunTracker.global_instance()
    reporting = Reporting.global_instance()

    with self.assertRaises(ValueError) as result:
      reporting.initialize(run_tracker, context.options)

    self.assertTrue(
      "Flags parent_id and zipkin_endpoint must be set if trace_id is given." in str(result.exception)
    )
