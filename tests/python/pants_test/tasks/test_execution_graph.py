# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import re
import unittest
from collections import defaultdict
from typing import Dict, List

from pants.backend.jvm.tasks.jvm_compile.execution_graph import (
    ExecutionFailure,
    ExecutionGraph,
    Job,
    JobExistsError,
    NoRootJobError,
    UnknownJobError,
)


class ImmediatelyExecutingPool:
    num_workers = 1

    def submit_async_work(self, work):
        work.func(*work.args_tuples[0])


class PrintLogger:
    def error(self, msg):
        print(msg)

    def debug(self, msg):
        print(msg)


class CapturingLogger:

    log_entries: Dict[str, List[str]] = defaultdict(list)

    def error(self, msg: str) -> None:
        self.log_entries["error"].append(msg)

    def debug(self, msg: str) -> None:
        self.log_entries["debug"].append(msg)


def passing_fn():
    pass


def raising_fn():
    raise Exception("I'm an error")


def base_error_raising_fn():
    raise BaseException("I'm a BaseException")


def raising_wrapper():
    raising_fn()


class ExecutionGraphTest(unittest.TestCase):
    def setUp(self):
        self.jobs_run = []

    def execute(self, exec_graph):
        exec_graph.execute(ImmediatelyExecutingPool(), PrintLogger())

    def job(self, name, fn, dependencies, size=0, on_success=None, on_failure=None):
        def recording_fn():
            self.jobs_run.append(name)
            fn()

        return Job(name, recording_fn, dependencies, size, on_success, on_failure)

    def test_single_job(self):
        exec_graph = ExecutionGraph([self.job("A", passing_fn, [])], False)

        self.execute(exec_graph)

        self.assertEqual(self.jobs_run, ["A"])

    def test_single_dependency(self):
        exec_graph = ExecutionGraph(
            [self.job("A", passing_fn, ["B"]), self.job("B", passing_fn, [])], False
        )
        self.execute(exec_graph)

        self.assertEqual(self.jobs_run, ["B", "A"])

    def test_simple_binary_tree(self):
        exec_graph = ExecutionGraph(
            [
                self.job("A", passing_fn, ["B", "C"]),
                self.job("B", passing_fn, []),
                self.job("C", passing_fn, []),
            ],
            False,
        )
        self.execute(exec_graph)

        self.assertEqual(self.jobs_run, ["B", "C", "A"])

    def test_simple_linear_dependencies(self):
        exec_graph = ExecutionGraph(
            [
                self.job("A", passing_fn, ["B"]),
                self.job("B", passing_fn, ["C"]),
                self.job("C", passing_fn, []),
            ],
            False,
        )

        self.execute(exec_graph)

        self.assertEqual(self.jobs_run, ["C", "B", "A"])

    def test_simple_unconnected(self):
        exec_graph = ExecutionGraph(
            [self.job("A", passing_fn, []), self.job("B", passing_fn, [])], False
        )

        self.execute(exec_graph)

        self.assertEqual(self.jobs_run, ["A", "B"])

    def test_simple_unconnected_tree(self):
        exec_graph = ExecutionGraph(
            [
                self.job("A", passing_fn, ["B"]),
                self.job("B", passing_fn, []),
                self.job("C", passing_fn, []),
            ],
            False,
        )

        self.execute(exec_graph)

        self.assertEqual(self.jobs_run, ["B", "C", "A"])

    def test_dependee_depends_on_dependency_of_its_dependency(self):
        exec_graph = ExecutionGraph(
            [
                self.job("A", passing_fn, ["B", "C"]),
                self.job("B", passing_fn, ["C"]),
                self.job("C", passing_fn, []),
            ],
            False,
        )

        self.execute(exec_graph)

        self.assertEqual(["C", "B", "A"], self.jobs_run)

    def test_one_failure_raises_exception(self):
        exec_graph = ExecutionGraph([self.job("A", raising_fn, [])], False)
        with self.assertRaises(ExecutionFailure) as cm:
            self.execute(exec_graph)

        self.assertEqual("Failed jobs: A", str(cm.exception))

    def test_base_exception_failure_raises_exception(self):
        # BaseException happens for lower level issues, not catching and propagating it makes debugging
        # difficult.
        exec_graph = ExecutionGraph([self.job("A", base_error_raising_fn, [])], False)
        with self.assertRaises(ExecutionFailure) as cm:
            self.execute(exec_graph)

        self.assertEqual("Failed jobs: A", str(cm.exception))

    def test_failure_of_dependency_does_not_run_dependents(self):
        exec_graph = ExecutionGraph(
            [self.job("A", passing_fn, ["F"]), self.job("F", raising_fn, [])], False
        )
        with self.assertRaises(ExecutionFailure) as cm:
            self.execute(exec_graph)

        self.assertEqual(["F"], self.jobs_run)
        self.assertEqual("Failed jobs: F", str(cm.exception))

    def test_failure_of_dependency_does_not_run_second_order_dependents(self):
        exec_graph = ExecutionGraph(
            [
                self.job("A", passing_fn, ["B"]),
                self.job("B", passing_fn, ["F"]),
                self.job("F", raising_fn, []),
            ],
            False,
        )
        with self.assertRaises(ExecutionFailure) as cm:
            self.execute(exec_graph)

        self.assertEqual(["F"], self.jobs_run)
        self.assertEqual("Failed jobs: F", str(cm.exception))

    def test_failure_of_one_leg_of_tree_does_not_cancel_other(self):
        # TODO do we want this behavior, or do we want to fail fast on the first failed job?
        exec_graph = ExecutionGraph(
            [
                self.job("B", passing_fn, []),
                self.job("F", raising_fn, ["B"]),
                self.job("A", passing_fn, ["B"]),
            ],
            False,
        )
        with self.assertRaises(ExecutionFailure) as cm:
            self.execute(exec_graph)

        self.assertTrue(self.jobs_run == ["B", "F", "A"] or self.jobs_run == ["B", "A", "F"])
        self.assertEqual("Failed jobs: F", str(cm.exception))

    def test_failure_of_disconnected_job_does_not_cancel_non_dependents(self):
        exec_graph = ExecutionGraph(
            [self.job("A", passing_fn, []), self.job("F", raising_fn, [])], False
        )
        with self.assertRaises(ExecutionFailure):
            self.execute(exec_graph)

        self.assertEqual(["A", "F"], self.jobs_run)

    def test_cycle_in_graph_causes_failure(self):
        with self.assertRaises(NoRootJobError) as cm:
            ExecutionGraph(
                [self.job("A", passing_fn, ["B"]), self.job("B", passing_fn, ["A"])], False
            )

        self.assertEqual(
            "Unexecutable graph: All scheduled jobs have dependencies. "
            "There must be a circular dependency.",
            str(cm.exception),
        )

    def test_non_existent_dependency_causes_failure(self):
        with self.assertRaises(UnknownJobError) as cm:
            ExecutionGraph([self.job("A", passing_fn, []), self.job("B", passing_fn, ["Z"])], False)

        self.assertEqual("Unexecutable graph: Undefined dependencies 'Z'", str(cm.exception))

    def test_on_success_callback_raises_error(self):
        exec_graph = ExecutionGraph([self.job("A", passing_fn, [], on_success=raising_fn)], False)

        with self.assertRaises(ExecutionFailure) as cm:
            self.execute(exec_graph)

        self.assertEqual("Error in on_success for A: I'm an error", str(cm.exception))

    def test_on_failure_callback_raises_error(self):
        exec_graph = ExecutionGraph([self.job("A", raising_fn, [], on_failure=raising_fn)], False)

        with self.assertRaises(ExecutionFailure) as cm:
            self.execute(exec_graph)

        self.assertEqual("Error in on_failure for A: I'm an error", str(cm.exception))

    def test_same_key_scheduled_twice_is_error(self):
        with self.assertRaises(JobExistsError) as cm:
            ExecutionGraph(
                [self.job("Same", passing_fn, []), self.job("Same", passing_fn, [])], False
            )

        self.assertEqual("Unexecutable graph: Job already scheduled 'Same'", str(cm.exception))

    def test_priorities_for_chain_of_jobs(self):
        exec_graph = ExecutionGraph(
            [
                self.job("A", passing_fn, [], 8),
                self.job("B", passing_fn, ["A"], 4),
                self.job("C", passing_fn, ["B"], 2),
                self.job("D", passing_fn, ["C"], 1),
            ],
            False,
        )
        self.assertEqual(exec_graph._job_priority, {"A": 15, "B": 7, "C": 3, "D": 1})
        self.execute(exec_graph)
        self.assertEqual(self.jobs_run, ["A", "B", "C", "D"])

    def test_priorities_for_fork(self):
        exec_graph = ExecutionGraph(
            [
                self.job("A", passing_fn, [], 4),
                self.job("B", passing_fn, ["A"], 2),
                self.job("C", passing_fn, ["A"], 1),
            ],
            False,
        )
        self.assertEqual(exec_graph._job_priority, {"A": 6, "B": 2, "C": 1})
        self.execute(exec_graph)
        self.assertEqual(self.jobs_run, ["A", "B", "C"])

    def test_priorities_for_mirrored_fork(self):
        exec_graph = ExecutionGraph(
            [
                self.job("A", passing_fn, [], 4),
                self.job("B", passing_fn, ["A"], 1),
                self.job("C", passing_fn, ["A"], 2),
            ],
            False,
        )
        self.assertEqual(exec_graph._job_priority, {"A": 6, "B": 1, "C": 2})
        self.execute(exec_graph)
        self.assertEqual(self.jobs_run, ["A", "C", "B"])

    def test_priorities_for_diamond(self):
        exec_graph = ExecutionGraph(
            [
                self.job("A", passing_fn, [], 8),
                self.job("B", passing_fn, ["A"], 4),
                self.job("C", passing_fn, ["A"], 2),
                self.job("D", passing_fn, ["B", "C"], 1),
            ],
            False,
        )
        self.assertEqual(exec_graph._job_priority, {"A": 13, "B": 5, "C": 3, "D": 1})
        self.execute(exec_graph)
        self.assertEqual(self.jobs_run, ["A", "B", "C", "D"])

    def test_priorities_for_mirrored_diamond(self):
        exec_graph = ExecutionGraph(
            [
                self.job("A", passing_fn, [], 8),
                self.job("B", passing_fn, ["A"], 2),
                self.job("C", passing_fn, ["A"], 4),
                self.job("D", passing_fn, ["B", "C"], 1),
            ],
            False,
        )
        self.assertEqual(exec_graph._job_priority, {"A": 13, "B": 3, "C": 5, "D": 1})
        self.execute(exec_graph)
        self.assertEqual(self.jobs_run, ["A", "C", "B", "D"])

    def test_priorities_for_skewed_diamond(self):
        exec_graph = ExecutionGraph(
            [
                self.job("A", passing_fn, [], 1),
                self.job("B", passing_fn, ["A"], 2),
                self.job("C", passing_fn, ["B"], 4),
                self.job("D", passing_fn, ["A"], 8),
                self.job("E", passing_fn, ["C", "D"], 16),
            ],
            False,
        )
        self.assertEqual(exec_graph._job_priority, {"A": 25, "B": 22, "C": 20, "D": 24, "E": 16})
        self.execute(exec_graph)
        self.assertEqual(self.jobs_run, ["A", "D", "B", "C", "E"])

    def test_jobs_not_canceled_multiple_times(self):
        failures = list()

        def collect_failure(jobname):
            def fn():
                failures.append(jobname)

            return fn

        def my_job(name, result_fn, deps):
            return self.job(name, result_fn, deps, 1, on_failure=collect_failure(name))

        exec_graph = ExecutionGraph(
            [
                my_job("A", raising_fn, []),
                my_job("B1", passing_fn, ["A"]),
                my_job("B2", passing_fn, ["A"]),
                my_job("C1", passing_fn, ["B1", "B2"]),
                my_job("C2", passing_fn, ["B1", "B2"]),
                my_job("E", passing_fn, ["C2"]),
            ],
            False,
        )

        with self.assertRaises(ExecutionFailure):
            self.execute(exec_graph)

        self.assertEqual(self.jobs_run, ["A"])
        self.assertEqual(failures, ["A", "B1", "B2", "C1", "C2", "E"])

    def test_dumps_stack_trace(self):
        graph = ExecutionGraph([self.job("A", raising_wrapper, [])], True)
        capturing_logger = CapturingLogger()
        with self.assertRaises(ExecutionFailure):
            graph.execute(ImmediatelyExecutingPool(), capturing_logger)
        error_logs = capturing_logger.log_entries["error"]
        self.assertEqual(2, len(error_logs), msg=f"Wanted one error log, got: {error_logs}")
        regex = re.compile("A failed: I'm an error.*")
        self.assertRegex(error_logs[0], regex)
        regex = re.compile(
            'Traceback:.*in raising_wrapper.*raise Exception\\("I\'m an error.*"\\)', re.DOTALL,
        )
        self.assertRegex(error_logs[1], regex)
