# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import unittest
from dataclasses import dataclass, field
from textwrap import dedent
from typing import List

from pants.engine.rules import RootRule, named_rule, rule
from pants.engine.scheduler import ExecutionError
from pants.engine.selectors import Get, MultiGet
from pants.reporting.streaming_workunit_handler import StreamingWorkunitHandler
from pants.testutil.engine.util import (
    assert_equal_with_printing,
    fmt_rule,
    fmt_rust_function,
    remove_locations_from_traceback,
)
from pants_test.engine.scheduler_test_base import SchedulerTestBase


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


@named_rule(name="fib")
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


@named_rule(name="rule_one")
async def rule_one_function(i: Input) -> Beta:
    """This rule should be the first one executed by the engine, and thus have no parent."""
    a = Alpha()
    o = await Get[Omega](Alpha, a)
    b = await Get[Beta](Omega, o)
    return b


@named_rule
async def rule_two(a: Alpha) -> Omega:
    """This rule should be invoked in the body of `rule_one` and therefore its workunit should be a
    child of `rule_one`'s workunit."""
    await Get[Gamma](Alpha, a)
    return Omega()


@named_rule(desc="Rule number 3")
async def rule_three(o: Omega) -> Beta:
    """This rule should be invoked in the body of `rule_one` and therefore its workunit should be a
    child of `rule_one`'s workunit."""
    return Beta()


@named_rule(desc="Rule number 4")
def rule_four(a: Alpha) -> Gamma:
    """This rule should be invoked in the body of `rule_two` and therefore its workunit should be a
    child of `rule_two`'s workunit."""
    return Gamma()


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
            "1 Exception encountered:\n  Exception: An exception for B", str(cm.exception)
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
                  Exception: An exception for B"""
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
                f"""
                1 Exception encountered:
                Computing Select(<{__name__}.B object at 0xEEEEEEEEE>, A)
                  Computing Task({fmt_rust_function(nested_raise)}(), <{__name__}.B object at 0xEEEEEEEEE>, A, true)
                    Throw(An exception for B)
                      Traceback (most recent call last):
                        File LOCATION-INFO, in call
                          val = func(*args)
                        File LOCATION-INFO, in nested_raise
                          fn_raises(x)
                        File LOCATION-INFO, in fn_raises
                          raise Exception(f"An exception for {{type(x).__name__}}")
                      Exception: An exception for B
                """
            ).lstrip()
            + "\n",
            remove_locations_from_traceback(str(cm.exception)),
        )

    def test_fork_context(self):
        # A smoketest that confirms that we can successfully enter and exit the fork context, which
        # implies acquiring and releasing all relevant Engine resources.
        expected = "42"

        def fork_context_body():
            return expected

        res = self.mk_scheduler().with_fork_context(fork_context_body)
        self.assertEquals(res, expected)

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
        rules = [
            RootRule(B),
        ]

        scheduler = self.scheduler(rules, include_trace_on_error=False)

        # No rules are available to compute A.
        with self.assertRaises(Exception) as cm:
            list(scheduler.product_request(A, subjects=[(B())]))

        self.assert_equal_with_printing(
            """No installed @rules return the type A. Is the @rule that you're expecting to run registered?""",
            str(cm.exception),
        )

    def test_non_existing_root_fails_differently(self):
        rules = [
            upcast,
        ]

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
        workunits: List[dict] = field(default_factory=list)
        finished: bool = False

        def add(self, workunits, **kwargs) -> None:
            if kwargs["finished"] is True:
                self.finished = True
            self.workunits.extend(workunits)

    def test_streaming_workunits_reporting(self):
        rules = [fib, RootRule(int)]
        scheduler = self.mk_scheduler(
            rules, include_trace_on_error=False, should_report_workunits=True
        )

        tracker = self.WorkunitTracker()
        handler = StreamingWorkunitHandler(
            scheduler, callbacks=[tracker.add], report_interval_seconds=0.01
        )
        with handler.session():
            scheduler.product_request(Fib, subjects=[0])

        # The execution of the single named @rule "fib" should be providing this one workunit.
        self.assertEquals(len(tracker.workunits), 1)

        tracker.workunits = []
        with handler.session():
            scheduler.product_request(Fib, subjects=[10])

        # Requesting a bigger fibonacci number will result in more rule executions and thus more reported workunits.
        # In this case, we expect 10 invocations of the `fib` rule.
        assert len(tracker.workunits) == 10
        assert tracker.finished

    def test_streaming_workunits_parent_id_and_rule_metadata(self):
        rules = [RootRule(Input), rule_one_function, rule_two, rule_three, rule_four]
        scheduler = self.mk_scheduler(
            rules, include_trace_on_error=False, should_report_workunits=True
        )
        tracker = self.WorkunitTracker()
        handler = StreamingWorkunitHandler(
            scheduler, callbacks=[tracker.add], report_interval_seconds=0.01
        )

        with handler.session():
            i = Input()
            scheduler.product_request(Beta, subjects=[i])

        assert tracker.finished

        r1 = next(item for item in tracker.workunits if item["name"] == "rule_one")
        r2 = next(item for item in tracker.workunits if item["name"] == "rule_two")
        r3 = next(item for item in tracker.workunits if item["name"] == "rule_three")
        r4 = next(item for item in tracker.workunits if item["name"] == "rule_four")

        assert r1.get("parent_id", None) is None
        assert r2["parent_id"] == r1["span_id"]
        assert r3["parent_id"] == r1["span_id"]
        assert r4["parent_id"] == r2["span_id"]

        assert r3["desc"] == "Rule number 3"
        assert r4["desc"] == "Rule number 4"
