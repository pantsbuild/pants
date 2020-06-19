# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import itertools
import time
import unittest
from dataclasses import dataclass, field
from textwrap import dedent
from typing import List, Optional

from pants.engine.fs import EMPTY_DIGEST
from pants.engine.internals.scheduler import ExecutionError
from pants.engine.internals.scheduler_test_base import SchedulerTestBase
from pants.engine.process import Process, ProcessResult
from pants.engine.rules import EngineAware, RootRule, rule
from pants.engine.selectors import Get, MultiGet
from pants.reporting.streaming_workunit_handler import (
    StreamingWorkunitContext,
    StreamingWorkunitHandler,
)
from pants.testutil.engine.util import (
    assert_equal_with_printing,
    fmt_rule,
    remove_locations_from_traceback,
)
from pants.testutil.test_base import TestBase
from pants.util.logging import LogLevel


class A:
    pass


class B:
    pass


class C:
    pass


class D:
    pass


def fn_raises(x):
    raise Exception(f"An exception for {type(x).__name__}")


@rule
def nested_raise(x: B) -> A:  # type: ignore[return]
    fn_raises(x)


@dataclass(frozen=True)
class Fib:
    val: int


@rule(desc="Fibonacci", level=LogLevel.INFO)
async def fib(n: int) -> Fib:
    if n < 2:
        return Fib(n)
    x, y = tuple(await MultiGet([Get[Fib](int(n - 2)), Get[Fib](int(n - 1))]))
    return Fib(x.val + y.val)


@dataclass(frozen=True)
class MyInt:
    val: int


@dataclass(frozen=True)
class MyFloat:
    val: float


@rule
def upcast(n: MyInt) -> MyFloat:
    return MyFloat(float(n.val))


# This set of dummy types and the following `@rule`s are intended to test that workunits are
# being generated correctly and with the correct parent-child relationships.


class Input:
    pass


class Alpha:
    pass


class Beta:
    pass


class Gamma:
    pass


class Omega:
    pass


class Epsilon:
    pass


@rule(canonical_name="rule_one", desc="Rule number 1", level=LogLevel.INFO)
async def rule_one_function(i: Input) -> Beta:
    """This rule should be the first one executed by the engine, and thus have no parent."""
    a = Alpha()
    o = await Get[Omega](Alpha, a)
    b = await Get[Beta](Omega, o)
    time.sleep(1)
    return b


@rule(desc="Rule number 2", level=LogLevel.INFO)
async def rule_two(a: Alpha) -> Omega:
    """This rule should be invoked in the body of `rule_one` and therefore its workunit should be a
    child of `rule_one`'s workunit."""
    await Get[Gamma](Alpha, a)
    return Omega()


@rule(desc="Rule number 3", level=LogLevel.INFO)
async def rule_three(o: Omega) -> Beta:
    """This rule should be invoked in the body of `rule_one` and therefore its workunit should be a
    child of `rule_one`'s workunit."""
    return Beta()


@rule(desc="Rule number 4", level=LogLevel.INFO)
def rule_four(a: Alpha) -> Gamma:
    """This rule should be invoked in the body of `rule_two` and therefore its workunit should be a
    child of `rule_two`'s workunit."""
    return Gamma()


@rule(desc="Rule A", level=LogLevel.INFO)
async def rule_A(i: Input) -> Alpha:
    o = Omega()
    a = await Get[Alpha](Omega, o)
    return a


@rule
async def rule_B(o: Omega) -> Alpha:
    e = Epsilon()
    a = await Get[Alpha](Epsilon, e)
    return a


@rule(desc="Rule C", level=LogLevel.INFO)
def rule_C(e: Epsilon) -> Alpha:
    return Alpha()


class EngineTest(unittest.TestCase, SchedulerTestBase):

    assert_equal_with_printing = assert_equal_with_printing

    def scheduler(self, rules, include_trace_on_error):
        return self.mk_scheduler(rules=rules, include_trace_on_error=include_trace_on_error)

    def test_recursive_multi_get(self):
        # Tests that a rule that "uses itself" multiple times per invoke works.
        rules = [
            fib,
            RootRule(int),
        ]

        (fib_10,) = self.mk_scheduler(rules=rules).product_request(Fib, subjects=[10])

        self.assertEqual(55, fib_10.val)

    def test_no_include_trace_error_raises_boring_error(self):
        rules = [
            RootRule(B),
            nested_raise,
        ]

        scheduler = self.scheduler(rules, include_trace_on_error=False)

        with self.assertRaises(ExecutionError) as cm:
            list(scheduler.product_request(A, subjects=[(B())]))

        self.assert_equal_with_printing(
            "1 Exception encountered:\n\n  Exception: An exception for B\n", str(cm.exception)
        )

    def test_no_include_trace_error_multiple_paths_raises_executionerror(self):
        rules = [
            RootRule(B),
            nested_raise,
        ]

        scheduler = self.scheduler(rules, include_trace_on_error=False)

        with self.assertRaises(ExecutionError) as cm:
            list(scheduler.product_request(A, subjects=[B(), B()]))

        self.assert_equal_with_printing(
            dedent(
                """
                2 Exceptions encountered:

                  Exception: An exception for B
                  Exception: An exception for B
                """
            ).lstrip(),
            str(cm.exception),
        )

    def test_include_trace_error_raises_error_with_trace(self):
        rules = [
            RootRule(B),
            nested_raise,
        ]

        scheduler = self.scheduler(rules, include_trace_on_error=True)
        with self.assertRaises(ExecutionError) as cm:
            list(scheduler.product_request(A, subjects=[(B())]))

        self.assert_equal_with_printing(
            dedent(
                """
                1 Exception encountered:

                Traceback (most recent call last):
                  File LOCATION-INFO, in nested_raise
                    fn_raises(x)
                  File LOCATION-INFO, in fn_raises
                    raise Exception(f"An exception for {type(x).__name__}")
                Exception: An exception for B
                """
            ).lstrip(),
            remove_locations_from_traceback(str(cm.exception)),
        )

    @unittest.skip("flaky: https://github.com/pantsbuild/pants/issues/6829")
    def test_trace_multi(self):
        # Tests that when multiple distinct failures occur, they are each rendered.

        @rule
        def d_from_b_nested_raise(b: B) -> D:  # type: ignore[return]
            fn_raises(b)

        @rule
        def c_from_b_nested_raise(b: B) -> C:  # type: ignore[return]
            fn_raises(b)

        @rule
        def a_from_c_and_d(c: C, d: D) -> A:
            return A()

        rules = [
            RootRule(B),
            d_from_b_nested_raise,
            c_from_b_nested_raise,
            a_from_c_and_d,
        ]

        scheduler = self.scheduler(rules, include_trace_on_error=True)
        with self.assertRaises(ExecutionError) as cm:
            list(scheduler.product_request(A, subjects=[(B())]))

        self.assert_equal_with_printing(
            dedent(
                f"""
                1 Exception encountered:
                Computing Select(<{__name__}..B object at 0xEEEEEEEEE>, A)
                  Computing Task(a_from_c_and_d(), <{__name__}..B object at 0xEEEEEEEEE>, A, true)
                    Computing Task(d_from_b_nested_raise(), <{__name__}..B object at 0xEEEEEEEEE>, =D, true)
                      Throw(An exception for B)
                        Traceback (most recent call last):
                          File LOCATION-INFO, in call
                            val = func(*args)
                          File LOCATION-INFO, in d_from_b_nested_raise
                            fn_raises(b)
                          File LOCATION-INFO, in fn_raises
                            raise Exception('An exception for {{}}'.format(type(x).__name__))
                        Exception: An exception for B


                Computing Select(<{__name__}..B object at 0xEEEEEEEEE>, A)
                  Computing Task(a_from_c_and_d(), <{__name__}..B object at 0xEEEEEEEEE>, A, true)
                    Computing Task(c_from_b_nested_raise(), <{__name__}..B object at 0xEEEEEEEEE>, =C, true)
                      Throw(An exception for B)
                        Traceback (most recent call last):
                          File LOCATION-INFO, in call
                            val = func(*args)
                          File LOCATION-INFO, in c_from_b_nested_raise
                            fn_raises(b)
                          File LOCATION-INFO, in fn_raises
                            raise Exception('An exception for {{}}'.format(type(x).__name__))
                        Exception: An exception for B
                """
            ).lstrip()
            + "\n",
            remove_locations_from_traceback(str(cm.exception)),
        )

    def test_illegal_root_selection(self):
        rules = [RootRule(B)]

        scheduler = self.scheduler(rules, include_trace_on_error=False)

        # No rules are available to compute A.
        with self.assertRaises(Exception) as cm:
            list(scheduler.product_request(A, subjects=[(B())]))

        self.assert_equal_with_printing(
            "No installed @rules return the type A. Is the @rule that you're expecting to run registered?",
            str(cm.exception),
        )

    def test_nonexistent_root_fails_differently(self):
        rules = [upcast]

        with self.assertRaises(Exception) as cm:
            list(self.mk_scheduler(rules=rules, include_trace_on_error=False))

        self.assert_equal_with_printing(
            dedent(
                f"""
                Rules with errors: 1

                  {fmt_rule(upcast)}:
                    No rule was available to compute MyInt. Maybe declare RootRule(MyInt)?
                """
            ).strip(),
            str(cm.exception),
        )


@dataclass
class WorkunitTracker:
    """This class records every non-empty batch of started and completed workunits received from the
    engine."""

    finished_workunit_chunks: List[List[dict]] = field(default_factory=list)
    started_workunit_chunks: List[List[dict]] = field(default_factory=list)
    finished: bool = False

    def add(self, workunits, **kwargs) -> None:
        if kwargs["finished"] is True:
            self.finished = True

        started_workunits = kwargs.get("started_workunits")
        if started_workunits:
            self.started_workunit_chunks.append(started_workunits)

        if workunits:
            self.finished_workunit_chunks.append(workunits)


class StreamingWorkunitTests(unittest.TestCase, SchedulerTestBase):
    def test_streaming_workunits_reporting(self):
        rules = [fib, RootRule(int)]
        scheduler = self.mk_scheduler(
            rules, include_trace_on_error=False, should_report_workunits=True
        )

        tracker = WorkunitTracker()
        handler = StreamingWorkunitHandler(
            scheduler,
            callbacks=[tracker.add],
            report_interval_seconds=0.01,
            max_workunit_verbosity=LogLevel.INFO,
        )
        with handler.session():
            scheduler.product_request(Fib, subjects=[0])

        flattened = list(itertools.chain.from_iterable(tracker.finished_workunit_chunks))
        # The execution of the single named @rule "fib" should be providing this one workunit.
        self.assertEqual(len(flattened), 1)

        tracker.finished_workunit_chunks = []
        with handler.session():
            scheduler.product_request(Fib, subjects=[10])

        # Requesting a bigger fibonacci number will result in more rule executions and thus more reported workunits.
        # In this case, we expect 10 invocations of the `fib` rule.
        flattened = list(itertools.chain.from_iterable(tracker.finished_workunit_chunks))
        assert len(flattened) == 10
        assert tracker.finished

    def test_streaming_workunits_parent_id_and_rule_metadata(self):
        rules = [RootRule(Input), rule_one_function, rule_two, rule_three, rule_four]
        scheduler = self.mk_scheduler(
            rules, include_trace_on_error=False, should_report_workunits=True
        )
        tracker = WorkunitTracker()
        handler = StreamingWorkunitHandler(
            scheduler,
            callbacks=[tracker.add],
            report_interval_seconds=0.01,
            max_workunit_verbosity=LogLevel.INFO,
        )

        with handler.session():
            i = Input()
            scheduler.product_request(Beta, subjects=[i])

        assert tracker.finished

        # rule_one should complete well-after the other rules because of the artificial delay in it caused by the sleep().
        assert {item["name"] for item in tracker.finished_workunit_chunks[0]} == {
            "rule_two",
            "rule_three",
            "rule_four",
        }

        # Because of the artificial delay in rule_one, it should have time to be reported as
        # started but not yet finished.
        started = list(itertools.chain.from_iterable(tracker.started_workunit_chunks))
        assert len(list(item for item in started if item["name"] == "rule_one")) > 0

        assert {item["name"] for item in tracker.finished_workunit_chunks[1]} == {"rule_one"}

        finished = list(itertools.chain.from_iterable(tracker.finished_workunit_chunks))

        r1 = next(item for item in finished if item["name"] == "rule_one")
        r2 = next(item for item in finished if item["name"] == "rule_two")
        r3 = next(item for item in finished if item["name"] == "rule_three")
        r4 = next(item for item in finished if item["name"] == "rule_four")

        # rule_one should have no parent_id because its actual parent workunit was filted based on level
        assert r1.get("parent_id", None) is None

        assert r2["parent_id"] == r1["span_id"]
        assert r3["parent_id"] == r1["span_id"]
        assert r4["parent_id"] == r2["span_id"]

        assert r3["description"] == "Rule number 3"
        assert r4["description"] == "Rule number 4"
        assert r4["level"] == "INFO"

    def test_streaming_workunit_log_levels(self) -> None:
        rules = [RootRule(Input), rule_one_function, rule_two, rule_three, rule_four]
        scheduler = self.mk_scheduler(
            rules, include_trace_on_error=False, should_report_workunits=True
        )
        tracker = WorkunitTracker()
        handler = StreamingWorkunitHandler(
            scheduler,
            callbacks=[tracker.add],
            report_interval_seconds=0.01,
            max_workunit_verbosity=LogLevel.TRACE,
        )

        with handler.session():
            i = Input()
            scheduler.product_request(Beta, subjects=[i])

        assert tracker.finished
        finished = list(itertools.chain.from_iterable(tracker.finished_workunit_chunks))

        # With the max_workunit_verbosity set to TRACE, we should see the workunit corresponding to the Select node.
        select = next(
            item
            for item in finished
            if item["name"] not in {"rule_one", "rule_two", "rule_three", "rule_four"}
        )
        assert select["name"] == "select"
        assert select["level"] == "DEBUG"

        r1 = next(item for item in finished if item["name"] == "rule_one")
        assert r1["parent_id"] == select["span_id"]

    def test_streaming_workunit_log_level_parent_rewrite(self) -> None:
        rules = [RootRule(Input), rule_A, rule_B, rule_C]
        scheduler = self.mk_scheduler(
            rules, include_trace_on_error=False, should_report_workunits=True
        )
        tracker = WorkunitTracker()
        info_level_handler = StreamingWorkunitHandler(
            scheduler,
            callbacks=[tracker.add],
            report_interval_seconds=0.01,
            max_workunit_verbosity=LogLevel.INFO,
        )

        with info_level_handler.session():
            i = Input()
            scheduler.product_request(Alpha, subjects=[i])

        assert tracker.finished
        finished = list(itertools.chain.from_iterable(tracker.finished_workunit_chunks))

        assert len(finished) == 2
        r_A = next(item for item in finished if item["name"] == "rule_A")
        r_C = next(item for item in finished if item["name"] == "rule_C")
        assert "parent_id" not in r_A
        assert r_C["parent_id"] == r_A["span_id"]

        scheduler = self.mk_scheduler(
            rules, include_trace_on_error=False, should_report_workunits=True
        )
        tracker = WorkunitTracker()
        debug_level_handler = StreamingWorkunitHandler(
            scheduler,
            callbacks=[tracker.add],
            report_interval_seconds=0.01,
            max_workunit_verbosity=LogLevel.DEBUG,
        )

        with debug_level_handler.session():
            i = Input()
            scheduler.product_request(Alpha, subjects=[i])

        assert tracker.finished
        finished = list(itertools.chain.from_iterable(tracker.finished_workunit_chunks))

        r_A = next(item for item in finished if item["name"] == "rule_A")
        r_B = next(item for item in finished if item["name"] == "rule_B")
        r_C = next(item for item in finished if item["name"] == "rule_C")
        assert r_B["parent_id"] == r_A["span_id"]
        assert r_C["parent_id"] == r_B["span_id"]

    def test_engine_aware_rule(self):
        @dataclass(frozen=True)
        class ModifiedOutput(EngineAware):
            _level: LogLevel
            val: int

            def level(self):
                return self._level

        @rule(desc="a_rule")
        def a_rule(n: int) -> ModifiedOutput:
            return ModifiedOutput(val=n, _level=LogLevel.ERROR)

        rules = [a_rule, RootRule(int)]
        scheduler = self.mk_scheduler(
            rules, include_trace_on_error=False, should_report_workunits=True
        )

        tracker = WorkunitTracker()
        handler = StreamingWorkunitHandler(
            scheduler,
            callbacks=[tracker.add],
            report_interval_seconds=0.01,
            max_workunit_verbosity=LogLevel.DEBUG,
        )
        with handler.session():
            scheduler.product_request(ModifiedOutput, subjects=[0])

        finished = list(itertools.chain.from_iterable(tracker.finished_workunit_chunks))
        workunit = next(item for item in finished if item["name"] == "a_rule")
        assert workunit["level"] == "ERROR"

    def test_engine_aware_none_case(self):
        @dataclass(frozen=True)
        # If level() returns None, the engine shouldn't try to set
        # a new workunit level.
        class ModifiedOutput(EngineAware):
            _level: Optional[LogLevel]
            val: int

            def level(self):
                return self._level

        @rule(desc="a_rule")
        def a_rule(n: int) -> ModifiedOutput:
            return ModifiedOutput(val=n, _level=None)

        rules = [a_rule, RootRule(int)]
        scheduler = self.mk_scheduler(
            rules, include_trace_on_error=False, should_report_workunits=True
        )

        tracker = WorkunitTracker()
        handler = StreamingWorkunitHandler(
            scheduler,
            callbacks=[tracker.add],
            report_interval_seconds=0.01,
            max_workunit_verbosity=LogLevel.DEBUG,
        )
        with handler.session():
            scheduler.product_request(ModifiedOutput, subjects=[0])

        finished = list(itertools.chain.from_iterable(tracker.finished_workunit_chunks))
        workunit = next(item for item in finished if item["name"] == "a_rule")
        assert workunit["level"] == "DEBUG"


class StreamingWorkunitProcessTests(TestBase):

    additional_options = ["--no-process-execution-use-local-cache"]

    def test_process_digests_on_workunits(self):
        scheduler = self.scheduler

        tracker = WorkunitTracker()
        handler = StreamingWorkunitHandler(
            scheduler,
            callbacks=[tracker.add],
            report_interval_seconds=0.01,
            max_workunit_verbosity=LogLevel.INFO,
        )

        stdout_process = Process(
            argv=("/bin/bash", "-c", "/bin/echo 'stdout output'"), description="Stdout process"
        )

        with handler.session():
            result = self.request_single_product(ProcessResult, stdout_process)

        assert tracker.finished
        finished = list(itertools.chain.from_iterable(tracker.finished_workunit_chunks))

        process_workunit = next(
            item for item in finished if item["name"] == "multi_platform_process-running"
        )
        assert process_workunit is not None
        stdout_digest = process_workunit["artifacts"]["stdout_digest"]
        stderr_digest = process_workunit["artifacts"]["stderr_digest"]

        assert result.stdout == b"stdout output\n"
        assert stderr_digest == EMPTY_DIGEST
        assert stdout_digest.serialized_bytes_length == len(result.stdout)

        tracker = WorkunitTracker()
        handler = StreamingWorkunitHandler(
            self._scheduler,
            callbacks=[tracker.add],
            report_interval_seconds=0.01,
            max_workunit_verbosity=LogLevel.INFO,
        )

        stderr_process = Process(
            argv=("/bin/bash", "-c", "1>&2 /bin/echo 'stderr output'"), description="Stderr process"
        )

        with handler.session():
            result = self.request_single_product(ProcessResult, stderr_process)

        assert tracker.finished
        finished = list(itertools.chain.from_iterable(tracker.finished_workunit_chunks))
        process_workunit = next(
            item for item in finished if item["name"] == "multi_platform_process-running"
        )

        assert process_workunit is not None
        stdout_digest = process_workunit["artifacts"]["stdout_digest"]
        stderr_digest = process_workunit["artifacts"]["stderr_digest"]

        assert result.stderr == b"stderr output\n"
        assert stdout_digest == EMPTY_DIGEST
        assert stderr_digest.serialized_bytes_length == len(result.stderr)

        try:
            self._scheduler.ensure_remote_has_recursive([stdout_digest, stderr_digest])
        except Exception as e:
            # This is the exception message we should expect from invoking ensure_remote_has_recursive()
            # in rust.
            assert str(e) == "Cannot ensure remote has blobs without a remote"

        byte_outputs = self._scheduler.digests_to_bytes([stdout_digest, stderr_digest])
        assert byte_outputs[0] == result.stdout
        assert byte_outputs[1] == result.stderr

    def test_context_object(self):
        scheduler = self.scheduler

        def callback(workunits, **kwargs) -> None:
            context = kwargs["context"]
            assert isinstance(context, StreamingWorkunitContext)

            for workunit in workunits:
                if "artifacts" in workunit and "stdout_digest" in workunit["artifacts"]:
                    digest = workunit["artifacts"]["stdout_digest"]
                    output = context.digests_to_bytes([digest])
                    assert output == (b"stdout output\n",)

        handler = StreamingWorkunitHandler(
            scheduler,
            callbacks=[callback],
            report_interval_seconds=0.01,
            max_workunit_verbosity=LogLevel.INFO,
        )

        stdout_process = Process(
            argv=("/bin/bash", "-c", "/bin/echo 'stdout output'"), description="Stdout process"
        )

        with handler.session():
            self.request_single_product(ProcessResult, stdout_process)
