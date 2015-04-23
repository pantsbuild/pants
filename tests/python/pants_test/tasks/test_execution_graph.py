# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import unittest

from pants.backend.jvm.tasks.jvm_compile.execution_graph import ExecutionGraph, Job


class ImmediatelyExecutingPool(object):
  def submit_async_work(self, work):
    work.func(*work.args_tuples[0])


class PrintLogger(object):
  def debug(self, msg):
    print(msg)


def passing_fn():
  pass


def raising_fn():
  raise Exception("I'm an error")


class ExecutionGraphTest(unittest.TestCase):
  def setUp(self):
    self.jobs_run = []

  def execute(self, exec_graph):
    exec_graph.execute(ImmediatelyExecutingPool(), PrintLogger())

  def job(self, name, fn, dependencies):
    def recording_fn():
      self.jobs_run.append(name)
      fn()

    return Job(name, recording_fn, dependencies)

  def test_single_job(self):
    exec_graph = ExecutionGraph([self.job("A", passing_fn, [])])

    self.execute(exec_graph)

    self.assertEqual(self.jobs_run, ["A"])

  def test_single_dependency(self):
    exec_graph = ExecutionGraph([self.job("A", passing_fn, ["B"]),
                                 self.job("B", passing_fn, [])])
    self.execute(exec_graph)

    self.assertEqual(self.jobs_run, ["B", "A"])

  # simple binary tree
  # A -> B
  # A -> C
  def test_simple_binary_tree(self):
    exec_graph = ExecutionGraph([self.job("A", passing_fn, ["B", "C"]),
                                 self.job("B", passing_fn, []),
                                 self.job("C", passing_fn, [])])
    self.execute(exec_graph)

    self.assertEqual(self.jobs_run, ["B", "C", "A"])

  # simple linear
  # A -> B
  # B -> C
  def test_simple_linear_dependencies(self):
    exec_graph = ExecutionGraph([self.job("A", passing_fn, ["B"]),
                                 self.job("B", passing_fn, ["C"]),
                                 self.job("C", passing_fn, [])])

    self.execute(exec_graph)

    self.assertEqual(self.jobs_run, ["C", "B", "A"])

  # A
  # B
  def test_simple_unconnected(self):
    exec_graph = ExecutionGraph([self.job("A", passing_fn, []),
                                 self.job("B", passing_fn, []),
    ])

    self.execute(exec_graph)

    self.assertEqual(self.jobs_run, ["A", "B"])

  # disconnected tree
  # A -> B
  # C
  def test_simple_unconnected_tree(self):
    exec_graph = ExecutionGraph([self.job("A", passing_fn, ["B"]),
                                 self.job("B", passing_fn, []),
                                 self.job("C", passing_fn, []),
    ])

    self.execute(exec_graph)

    self.assertEqual(self.jobs_run, ["B", "C", "A"])


    # dependee depends on dependency of its dependency

  # A -> B
  # A -> C
  # B -> C
  def test_dependee_depends_on_dependency_of_its_dependency(self):
    exec_graph = ExecutionGraph([self.job("A", passing_fn, ["B", "C"]),
                                 self.job("B", passing_fn, ["C"]),
                                 self.job("C", passing_fn, []),
    ])

    self.execute(exec_graph)

    self.assertEqual(["C", "B", "A"], self.jobs_run)
  
  def test_one_failure_raises_exception(self):
    exec_graph = ExecutionGraph([self.job("A", raising_fn, [])])
    with self.assertRaises(ExecutionGraph.ExecutionFailure) as cm:
      self.execute(exec_graph)

    self.assertEqual("Failed jobs: A", str(cm.exception))

  def test_failure_of_dependency_does_not_run_dependents(self):
    exec_graph = ExecutionGraph([self.job("A", raising_fn, ["F"]),
                                 self.job("F", raising_fn, [])])
    with self.assertRaises(ExecutionGraph.ExecutionFailure) as cm:
      self.execute(exec_graph)
  
    self.assertEqual(["F"], self.jobs_run)

  #def test_failure_of_dependency_does_not_include_dependents_in_error_message(self):
  #  exec_graph = ExecutionGraph([self.job("A", raising_fn, ["F"]),
  #                               self.job("F", raising_fn, [])])
  #  with self.assertRaises(ExecutionGraph.ExecutionFailure) as cm:
  #    self.execute(exec_graph)
#
  #  self.assertEqual("Failed jobs: F", str(cm.exception))

  def test_failure_of_disconnected_job_does_not_cancel_non_dependents(self):
    exec_graph = ExecutionGraph([self.job("A", passing_fn, []),
                                 self.job("F", raising_fn, [])])
    with self.assertRaises(ExecutionGraph.ExecutionFailure):
      self.execute(exec_graph)

    self.assertEqual(["A", "F"], self.jobs_run)

  def test_cycle_in_graph_causes_failure(self):

    with self.assertRaises(ValueError) as cm:
      ExecutionGraph([self.job("A", passing_fn, ["B"]),
                      self.job("B", passing_fn, ["A"])])

    self.assertEqual("No jobs without dependencies! There must be a circular dependency",
                     str(cm.exception))

  def test_non_existent_dependency_causes_failure(self):
    with self.assertRaises(ValueError) as cm:
      ExecutionGraph([self.job("A", passing_fn, []),
                      self.job("B", passing_fn, ["Z"])])

    self.assertEqual("Unscheduled dependencies: Z", str(cm.exception))


# simple binary tree, one dependency fails
# A -> (B)
# A -> C
# C succeeds
# A marked as transitive failure
# B direct failure

# simple linear, inner dependency fails
# A -> (B)
# (B) -> C


# exception handling
# unsorted scheduling, is fine if resolved by execution
# A -> B
# schedule A # blows up because B not scheduled yet
# schedule B

# cycles
# A -> B
# B -> A
# scheduling should probably fail because it's impossible to have scheduled the other

# on_success / failure raises
# schedule job with existing key
# do something with exceptions that bubble up from failed jobs
# break out a transitive failure state called canceled
