# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import itertools
import time
from dataclasses import dataclass, field
from pathlib import Path
from textwrap import dedent
from typing import List, Optional, Tuple

import pytest

from pants.backend.python.target_types import PythonSourcesGeneratorTarget
from pants.base.exceptions import IntrinsicError
from pants.base.specs import Specs
from pants.base.specs_parser import SpecsParser
from pants.engine.engine_aware import EngineAwareParameter, EngineAwareReturnType
from pants.engine.fs import (
    EMPTY_FILE_DIGEST,
    EMPTY_SNAPSHOT,
    CreateDigest,
    Digest,
    DigestContents,
    FileContent,
    MergeDigests,
    Snapshot,
)
from pants.engine.internals.engine_testutil import (
    assert_equal_with_printing,
    remove_locations_from_traceback,
)
from pants.engine.internals.scheduler import ExecutionError, SchedulerSession
from pants.engine.internals.scheduler_test_base import SchedulerTestBase
from pants.engine.process import Process, ProcessCacheScope, ProcessResult
from pants.engine.rules import Get, MultiGet, rule
from pants.engine.streaming_workunit_handler import (
    StreamingWorkunitContext,
    StreamingWorkunitHandler,
    TargetInfo,
    WorkunitsCallback,
)
from pants.engine.unions import UnionRule, union
from pants.goal.run_tracker import RunTracker
from pants.testutil.option_util import create_options_bootstrapper
from pants.testutil.rule_runner import QueryRule, RuleRunner, engine_error
from pants.util.logging import LogLevel
from pants.util.strutil import softwrap


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


@dataclass(frozen=True)
class MyInt:
    val: int


@rule(desc="Fibonacci", level=LogLevel.INFO)
async def fib(n: MyInt) -> Fib:
    if n.val < 2:
        return Fib(n.val)
    x, y = tuple(await MultiGet([Get(Fib, MyInt(n.val - 2)), Get(Fib, MyInt(n.val - 1))]))
    return Fib(x.val + y.val)


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


@rule(canonical_name="canonical_rule_one", desc="Rule number 1", level=LogLevel.INFO)
async def rule_one_function(i: Input) -> Beta:
    """This rule should be the first one executed by the engine, and thus have no parent."""
    a = Alpha()
    o = await Get(Omega, Alpha, a)
    b = await Get(Beta, Omega, o)
    time.sleep(1)
    return b


@rule(desc="Rule number 2", level=LogLevel.INFO)
async def rule_two(a: Alpha) -> Omega:
    """This rule should be invoked in the body of `rule_one` and therefore its workunit should be a
    child of `rule_one`'s workunit."""
    await Get(Gamma, Alpha, a)
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
    a = await Get(Alpha, Omega, o)
    return a


@rule
async def rule_B(o: Omega) -> Alpha:
    e = Epsilon()
    a = await Get(Alpha, Epsilon, e)
    return a


@rule(desc="Rule C", level=LogLevel.INFO)
def rule_C(e: Epsilon) -> Alpha:
    return Alpha()


class TestEngine(SchedulerTestBase):
    def scheduler(self, tmp_path: Path, rules, include_trace_on_error):
        return self.mk_scheduler(
            tmp_path, rules=rules, include_trace_on_error=include_trace_on_error
        )

    def test_recursive_multi_get(self, tmp_path: Path) -> None:
        # Tests that a rule that "uses itself" multiple times per invoke works.
        rules = [fib, QueryRule(Fib, (MyInt,))]
        (fib_10,) = self.mk_scheduler(tmp_path, rules=rules).product_request(
            Fib, subjects=[MyInt(10)]
        )
        assert 55 == fib_10.val

    def test_no_include_trace_error_raises_boring_error(self, tmp_path: Path) -> None:
        rules = [nested_raise, QueryRule(A, (B,))]
        scheduler = self.scheduler(tmp_path, rules, include_trace_on_error=False)
        with pytest.raises(ExecutionError) as cm:
            list(scheduler.product_request(A, subjects=[(B())]))
        assert_equal_with_printing(
            "1 Exception encountered:\n\nException: An exception for B\n", str(cm.value)
        )

    def test_no_include_trace_error_multiple_paths_raises_executionerror(
        self, tmp_path: Path
    ) -> None:
        rules = [nested_raise, QueryRule(A, (B,))]
        scheduler = self.scheduler(tmp_path, rules, include_trace_on_error=False)
        with pytest.raises(ExecutionError) as cm:
            list(scheduler.product_request(A, subjects=[B(), B()]))
        assert_equal_with_printing(
            dedent(
                """
                2 Exceptions encountered:

                Exception: An exception for B

                (and 1 more)
                """
            ).lstrip(),
            str(cm.value),
        )

    def test_include_trace_error_raises_error_with_trace(self, tmp_path: Path) -> None:
        rules = [nested_raise, QueryRule(A, (B,))]
        scheduler = self.scheduler(tmp_path, rules, include_trace_on_error=True)
        with pytest.raises(ExecutionError) as cm:
            list(scheduler.product_request(A, subjects=[(B())]))
        assert_equal_with_printing(
            dedent(
                """
                1 Exception encountered:

                Engine traceback:
                  in select
                    ..
                  in pants.engine.internals.engine_test.nested_raise
                    ..

                Traceback (most recent call last):
                  File LOCATION-INFO, in nested_raise
                    fn_raises(x)
                  File LOCATION-INFO, in fn_raises
                    raise Exception(f"An exception for {type(x).__name__}")
                Exception: An exception for B

                """
            ).lstrip(),
            remove_locations_from_traceback(str(cm.value)),
        )

    def test_nonexistent_root(self, tmp_path: Path) -> None:
        rules = [QueryRule(A, [B])]
        # No rules are available to compute A.
        with pytest.raises(ValueError) as cm:
            self.scheduler(tmp_path, rules, include_trace_on_error=False)
        assert (
            "No installed rules return the type A, and it was not provided by potential callers of "
        ) in str(cm.value)

    def test_missing_query_rule(self, tmp_path: Path) -> None:
        # Even if we register the rule to go from MyInt -> MyFloat, we must register a QueryRule
        # for the graph to work when making a synchronous call via `Scheduler.product_request`.
        scheduler = self.mk_scheduler(tmp_path, rules=[upcast], include_trace_on_error=False)
        with pytest.raises(Exception) as cm:
            scheduler.product_request(MyFloat, subjects=[MyInt(0)])
        assert (
            "No installed QueryRules return the type MyFloat. Try registering QueryRule(MyFloat "
            "for MyInt)."
        ) in str(cm.value)


@dataclass
class WorkunitTracker(WorkunitsCallback):
    """This class records every non-empty batch of started and completed workunits received from the
    engine."""

    finished_workunit_chunks: List[List[dict]] = field(default_factory=list)
    started_workunit_chunks: List[List[dict]] = field(default_factory=list)
    finished: bool = False

    @property
    def can_finish_async(self) -> bool:
        return False

    def __call__(self, **kwargs) -> None:
        if kwargs["finished"] is True:
            self.finished = True

        started_workunits = kwargs.get("started_workunits")
        if started_workunits:
            self.started_workunit_chunks.append(started_workunits)

        completed_workunits = kwargs.get("completed_workunits")
        if completed_workunits:
            self.finished_workunit_chunks.append(completed_workunits)


def new_run_tracker() -> RunTracker:
    # NB: A RunTracker usually observes "all options" (`full_options_for_scopes`), but it only
    # actually directly consumes bootstrap options.
    ob = create_options_bootstrapper([])
    return RunTracker(ob.args, ob.bootstrap_options)


@pytest.fixture
def run_tracker() -> RunTracker:
    return new_run_tracker()


class TestStreamingWorkunit(SchedulerTestBase):
    def _fixture_for_rules(
        self, tmp_path: Path, rules, max_workunit_verbosity: LogLevel = LogLevel.INFO
    ) -> Tuple[SchedulerSession, WorkunitTracker, StreamingWorkunitHandler]:
        scheduler = self.mk_scheduler(
            tmp_path,
            rules,
            include_trace_on_error=False,
            max_workunit_verbosity=max_workunit_verbosity,
        )
        tracker = WorkunitTracker()
        handler = StreamingWorkunitHandler(
            scheduler,
            run_tracker=new_run_tracker(),
            callbacks=[tracker],
            report_interval_seconds=0.01,
            max_workunit_verbosity=max_workunit_verbosity,
            specs=Specs.empty(),
            options_bootstrapper=create_options_bootstrapper([]),
            allow_async_completion=False,
        )
        return scheduler, tracker, handler

    def test_streaming_workunits_reporting(self, tmp_path: Path) -> None:
        scheduler, tracker, handler = self._fixture_for_rules(
            tmp_path / "start", [fib, QueryRule(Fib, (MyInt,))]
        )
        with handler:
            scheduler.product_request(Fib, subjects=[MyInt(0)])
        flattened = list(itertools.chain.from_iterable(tracker.finished_workunit_chunks))
        # The execution of the single named @rule "fib" should be providing this one workunit.
        assert len(flattened) == 1

        scheduler, tracker, handler = self._fixture_for_rules(
            tmp_path / "second", [fib, QueryRule(Fib, (MyInt,))]
        )
        with handler:
            scheduler.product_request(Fib, subjects=[MyInt(10)])

        # Requesting a bigger fibonacci number will result in more rule executions and thus
        # more reported workunits. In this case, we expect 11 invocations of the `fib` rule.
        flattened = list(itertools.chain.from_iterable(tracker.finished_workunit_chunks))
        assert len(flattened) == 11
        assert tracker.finished

    def test_streaming_workunits_parent_id_and_rule_metadata(self, tmp_path: Path) -> None:
        scheduler, tracker, handler = self._fixture_for_rules(
            tmp_path,
            [rule_one_function, rule_two, rule_three, rule_four, QueryRule(Beta, (Input,))],
        )
        with handler:
            i = Input()
            scheduler.product_request(Beta, subjects=[i])
        assert tracker.finished

        # rule_one should complete well-after the other rules because of the artificial delay in
        # it caused by the sleep().
        assert {item["name"] for item in tracker.finished_workunit_chunks[0]} == {
            "pants.engine.internals.engine_test.rule_two",
            "pants.engine.internals.engine_test.rule_three",
            "pants.engine.internals.engine_test.rule_four",
        }

        # Because of the artificial delay in rule_one, it should have time to be reported as
        # started but not yet finished.
        started = list(itertools.chain.from_iterable(tracker.started_workunit_chunks))
        assert len([item for item in started if item["name"] == "canonical_rule_one"]) > 0

        assert {item["name"] for item in tracker.finished_workunit_chunks[1]} == {
            "canonical_rule_one"
        }

        finished = list(itertools.chain.from_iterable(tracker.finished_workunit_chunks))

        r1 = next(item for item in finished if item["name"] == "canonical_rule_one")
        r2 = next(
            item
            for item in finished
            if item["name"] == "pants.engine.internals.engine_test.rule_two"
        )
        r3 = next(
            item
            for item in finished
            if item["name"] == "pants.engine.internals.engine_test.rule_three"
        )
        r4 = next(
            item
            for item in finished
            if item["name"] == "pants.engine.internals.engine_test.rule_four"
        )

        # rule_one should have no parent_id because its actual parent workunit was filtered based
        # on level.
        assert r1.get("parent_id", None) is None

        assert r2["parent_id"] == r1["span_id"]
        assert r3["parent_id"] == r1["span_id"]
        assert r4["parent_id"] == r2["span_id"]

        assert r3["description"] == "Rule number 3"
        assert r4["description"] == "Rule number 4"
        assert r4["level"] == "INFO"

    def test_streaming_workunit_log_levels(self, tmp_path: Path) -> None:
        scheduler, tracker, handler = self._fixture_for_rules(
            tmp_path,
            [rule_one_function, rule_two, rule_three, rule_four, QueryRule(Beta, (Input,))],
            max_workunit_verbosity=LogLevel.TRACE,
        )
        with handler:
            i = Input()
            scheduler.product_request(Beta, subjects=[i])

        assert tracker.finished
        finished = list(itertools.chain.from_iterable(tracker.finished_workunit_chunks))

        # With the max_workunit_verbosity set to TRACE, we should see the workunit corresponding
        # to the Select node.
        select = next(
            item
            for item in finished
            if item["name"]
            not in {
                "canonical_rule_one",
                "pants.engine.internals.engine_test.rule_two",
                "pants.engine.internals.engine_test.rule_three",
                "pants.engine.internals.engine_test.rule_four",
            }
        )
        assert select["name"] == "select"
        assert select["level"] == "TRACE"

        r1 = next(item for item in finished if item["name"] == "canonical_rule_one")
        assert r1["parent_id"] == select["span_id"]

    def test_streaming_workunit_log_level_parent_rewrite(self, tmp_path: Path) -> None:
        rules = [rule_A, rule_B, rule_C, QueryRule(Alpha, (Input,))]

        scheduler, tracker, info_level_handler = self._fixture_for_rules(tmp_path, rules)
        with info_level_handler:
            i = Input()
            scheduler.product_request(Alpha, subjects=[i])

        assert tracker.finished
        finished = list(itertools.chain.from_iterable(tracker.finished_workunit_chunks))

        assert len(finished) == 2
        r_A = next(
            item for item in finished if item["name"] == "pants.engine.internals.engine_test.rule_A"
        )
        r_C = next(
            item for item in finished if item["name"] == "pants.engine.internals.engine_test.rule_C"
        )
        assert "parent_id" not in r_A
        assert r_C["parent_id"] == r_A["span_id"]

        scheduler, tracker, debug_level_handler = self._fixture_for_rules(
            tmp_path, rules, max_workunit_verbosity=LogLevel.TRACE
        )
        with debug_level_handler:
            i = Input()
            scheduler.product_request(Alpha, subjects=[i])

        assert tracker.finished
        finished = list(itertools.chain.from_iterable(tracker.finished_workunit_chunks))

        r_A = next(
            item for item in finished if item["name"] == "pants.engine.internals.engine_test.rule_A"
        )
        r_B = next(
            item for item in finished if item["name"] == "pants.engine.internals.engine_test.rule_B"
        )
        r_C = next(
            item for item in finished if item["name"] == "pants.engine.internals.engine_test.rule_C"
        )
        assert r_B["parent_id"] == r_A["span_id"]
        assert r_C["parent_id"] == r_B["span_id"]

    def test_engine_aware_rule(self, tmp_path: Path) -> None:
        @dataclass(frozen=True)
        class ModifiedOutput(EngineAwareReturnType):
            _level: LogLevel
            val: int

            def level(self):
                return self._level

        @rule(desc="a_rule")
        def a_rule(n: MyInt) -> ModifiedOutput:
            return ModifiedOutput(val=n.val, _level=LogLevel.ERROR)

        scheduler, tracker, handler = self._fixture_for_rules(
            tmp_path,
            [a_rule, QueryRule(ModifiedOutput, (MyInt,))],
            max_workunit_verbosity=LogLevel.TRACE,
        )
        with handler:
            scheduler.product_request(ModifiedOutput, subjects=[MyInt(0)])

        finished = list(itertools.chain.from_iterable(tracker.finished_workunit_chunks))
        workunit = next(
            item
            for item in finished
            if item["name"]
            == "pants.engine.internals.engine_test.TestStreamingWorkunit.test_engine_aware_rule.a_rule"
        )
        assert workunit["level"] == "ERROR"

    def test_engine_aware_param(self, tmp_path: Path) -> None:
        @dataclass(frozen=True)
        class ModifiedMetadata(EngineAwareParameter):
            def metadata(self):
                return {"example": "thing"}

        @rule
        def a_rule(_: ModifiedMetadata) -> int:
            return 1

        scheduler, tracker, handler = self._fixture_for_rules(
            tmp_path,
            [a_rule, QueryRule(int, (ModifiedMetadata,))],
            max_workunit_verbosity=LogLevel.TRACE,
        )
        with handler:
            scheduler.product_request(int, subjects=[ModifiedMetadata()])

        finished = list(itertools.chain.from_iterable(tracker.finished_workunit_chunks))
        workunit = next(
            item
            for item in finished
            if item["name"]
            == "pants.engine.internals.engine_test.TestStreamingWorkunit.test_engine_aware_param.a_rule"
        )
        assert workunit["metadata"] == {"example": "thing"}

    def test_engine_aware_none_case(self, tmp_path: Path) -> None:
        @dataclass(frozen=True)
        # If level() returns None, the engine shouldn't try to set
        # a new workunit level.
        class ModifiedOutput(EngineAwareReturnType):
            _level: Optional[LogLevel]
            val: int

            def level(self):
                return self._level

        @rule(desc="a_rule")
        def a_rule(n: MyInt) -> ModifiedOutput:
            return ModifiedOutput(val=n.val, _level=None)

        scheduler, tracker, handler = self._fixture_for_rules(
            tmp_path,
            [a_rule, QueryRule(ModifiedOutput, (MyInt,))],
            max_workunit_verbosity=LogLevel.TRACE,
        )
        with handler:
            scheduler.product_request(ModifiedOutput, subjects=[MyInt(0)])

        finished = list(itertools.chain.from_iterable(tracker.finished_workunit_chunks))
        workunit = next(
            item
            for item in finished
            if item["name"]
            == "pants.engine.internals.engine_test.TestStreamingWorkunit.test_engine_aware_none_case.a_rule"
        )
        assert workunit["level"] == "TRACE"

    def test_artifacts_on_engine_aware_type(self, tmp_path: Path) -> None:
        @dataclass(frozen=True)
        class Output(EngineAwareReturnType):
            val: int

            def artifacts(self):
                return {"some_arbitrary_key": EMPTY_SNAPSHOT}

        @rule(desc="a_rule")
        def a_rule(n: MyInt) -> Output:
            return Output(val=n.val)

        scheduler, tracker, handler = self._fixture_for_rules(
            tmp_path, [a_rule, QueryRule(Output, (MyInt,))], max_workunit_verbosity=LogLevel.TRACE
        )
        with handler:
            scheduler.product_request(Output, subjects=[MyInt(0)])

        finished = list(itertools.chain.from_iterable(tracker.finished_workunit_chunks))
        workunit = next(
            item
            for item in finished
            if item["name"]
            == "pants.engine.internals.engine_test.TestStreamingWorkunit.test_artifacts_on_engine_aware_type.a_rule"
        )
        artifacts = workunit["artifacts"]
        assert artifacts["some_arbitrary_key"] == EMPTY_SNAPSHOT

    def test_metadata_on_engine_aware_type(self, tmp_path: Path) -> None:
        @dataclass(frozen=True)
        class Output(EngineAwareReturnType):
            val: int

            def metadata(self):
                return {"k1": 1, "k2": "a string", "k3": [1, 2, 3]}

        @rule(desc="a_rule")
        def a_rule(n: MyInt) -> Output:
            return Output(val=n.val)

        scheduler, tracker, handler = self._fixture_for_rules(
            tmp_path, [a_rule, QueryRule(Output, (MyInt,))], max_workunit_verbosity=LogLevel.TRACE
        )
        with handler:
            scheduler.product_request(Output, subjects=[MyInt(0)])

        finished = list(itertools.chain.from_iterable(tracker.finished_workunit_chunks))
        workunit = next(
            item
            for item in finished
            if item["name"]
            == "pants.engine.internals.engine_test.TestStreamingWorkunit.test_metadata_on_engine_aware_type.a_rule"
        )

        metadata = workunit["metadata"]
        assert metadata == {"k1": 1, "k2": "a string", "k3": [1, 2, 3]}

    def test_metadata_non_string_key_behavior(self, tmp_path: Path) -> None:
        # If someone passes a non-string key in a metadata() method,
        # this should fail to produce a meaningful metadata entry on
        # the workunit (with a warning), but not fail.

        @dataclass(frozen=True)
        class Output(EngineAwareReturnType):
            val: int

            def metadata(self):
                return {10: "foo", "other_key": "other value"}

        @rule(desc="a_rule")
        def a_rule(n: MyInt) -> Output:
            return Output(val=n.val)

        scheduler, tracker, handler = self._fixture_for_rules(
            tmp_path, [a_rule, QueryRule(Output, (MyInt,))], max_workunit_verbosity=LogLevel.TRACE
        )
        with handler:
            scheduler.product_request(Output, subjects=[MyInt(0)])

        finished = list(itertools.chain.from_iterable(tracker.finished_workunit_chunks))
        workunit = next(
            item
            for item in finished
            if item["name"]
            == "pants.engine.internals.engine_test.TestStreamingWorkunit.test_metadata_non_string_key_behavior.a_rule"
        )

        assert workunit["metadata"] == {}


@dataclass(frozen=True)
class ComplicatedInput:
    snapshot_1: Snapshot
    snapshot_2: Snapshot


@dataclass(frozen=True)
class Output(EngineAwareReturnType):
    snapshot_1: Snapshot
    snapshot_2: Snapshot

    def artifacts(self):
        return {"snapshot_1": self.snapshot_1, "snapshot_2": self.snapshot_2}


@rule(desc="a_rule", level=LogLevel.DEBUG)
def a_rule(input: ComplicatedInput) -> Output:
    return Output(snapshot_1=input.snapshot_1, snapshot_2=input.snapshot_2)


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            a_rule,
            QueryRule(Output, (ComplicatedInput,)),
            QueryRule(ProcessResult, (Process,)),
        ],
        isolated_local_store=True,
        # NB: The Sessions's configured verbosity is applied before a `StreamingWorkunitHandler`
        # can poll, and prevents things from being stored at all. So in order to observe TRACE
        # workunits in a poll, we must also configure TRACE on the Session.
        max_workunit_verbosity=LogLevel.TRACE,
    )


def test_counters(rule_runner: RuleRunner, run_tracker: RunTracker) -> None:
    scheduler = rule_runner.scheduler

    tracker = WorkunitTracker()
    handler = StreamingWorkunitHandler(
        scheduler,
        run_tracker=run_tracker,
        callbacks=[tracker],
        report_interval_seconds=0.01,
        max_workunit_verbosity=LogLevel.TRACE,
        specs=Specs.empty(),
        options_bootstrapper=create_options_bootstrapper([]),
        allow_async_completion=False,
    )

    with handler:
        scheduler.record_test_observation(128)
        rule_runner.request(
            ProcessResult,
            [
                Process(
                    ["/bin/sh", "-c", "true"],
                    description="always true",
                    cache_scope=ProcessCacheScope.PER_SESSION,
                )
            ],
        )
        metrics_info = scheduler.get_metrics()
        histograms_info = scheduler.get_observation_histograms()

    assert metrics_info["local_cache_requests"] == 1
    assert metrics_info["local_cache_requests_uncached"] == 1
    assert metrics_info["local_execution_requests"] == 1

    assert histograms_info["version"] == 0
    assert "histograms" in histograms_info
    assert "test_observation" in histograms_info["histograms"]
    assert (
        histograms_info["histograms"]["test_observation"]
        == b"\x1c\x84\x93\x14\x00\x00\x00\x1fx\x9c\x93i\x99,\xcc\xc0\xc0\xc0\xcc\x00\x010\x9a\x11J3\xd9\x7f\x800\xfe32\x01\x00E\x0c\x03\x81"
    )


def test_more_complicated_engine_aware(rule_runner: RuleRunner, run_tracker: RunTracker) -> None:
    tracker = WorkunitTracker()
    handler = StreamingWorkunitHandler(
        rule_runner.scheduler,
        run_tracker=run_tracker,
        callbacks=[tracker],
        report_interval_seconds=0.01,
        max_workunit_verbosity=LogLevel.TRACE,
        specs=Specs.empty(),
        options_bootstrapper=create_options_bootstrapper([]),
        allow_async_completion=False,
    )
    with handler:
        input_1 = CreateDigest(
            (
                FileContent(path="a.txt", content=b"alpha"),
                FileContent(path="b.txt", content=b"beta"),
            )
        )
        digest_1 = rule_runner.request(Digest, [input_1])
        snapshot_1 = rule_runner.request(Snapshot, [digest_1])

        input_2 = CreateDigest((FileContent(path="g.txt", content=b"gamma"),))
        digest_2 = rule_runner.request(Digest, [input_2])
        snapshot_2 = rule_runner.request(Snapshot, [digest_2])

        input = ComplicatedInput(snapshot_1=snapshot_1, snapshot_2=snapshot_2)

        rule_runner.request(Output, [input])

    finished = list(itertools.chain.from_iterable(tracker.finished_workunit_chunks))
    workunit = next(
        item for item in finished if item["name"] == "pants.engine.internals.engine_test.a_rule"
    )

    artifacts = workunit["artifacts"]
    output_snapshot_1 = artifacts["snapshot_1"]
    output_snapshot_2 = artifacts["snapshot_2"]

    output_contents_list = handler.context.snapshots_to_file_contents(
        [output_snapshot_1, output_snapshot_2]
    )
    assert len(output_contents_list) == 2

    assert isinstance(output_contents_list[0], DigestContents)
    assert isinstance(output_contents_list[1], DigestContents)

    digest_contents_1 = output_contents_list[0]
    digest_contents_2 = output_contents_list[1]

    assert len(tuple(x for x in digest_contents_1 if x.content == b"alpha")) == 1
    assert len(tuple(x for x in digest_contents_1 if x.content == b"beta")) == 1

    assert len(tuple(x for x in digest_contents_2 if x.content == b"gamma")) == 1


def test_process_digests_on_streaming_workunits(
    rule_runner: RuleRunner, run_tracker: RunTracker
) -> None:
    scheduler = rule_runner.scheduler

    tracker = WorkunitTracker()
    handler = StreamingWorkunitHandler(
        scheduler,
        run_tracker=run_tracker,
        callbacks=[tracker],
        report_interval_seconds=0.01,
        max_workunit_verbosity=LogLevel.DEBUG,
        specs=Specs.empty(),
        options_bootstrapper=create_options_bootstrapper([]),
        allow_async_completion=False,
    )

    stdout_process = Process(
        argv=("/bin/bash", "-c", "/bin/echo 'stdout output'"), description="Stdout process"
    )

    with handler:
        result = rule_runner.request(ProcessResult, [stdout_process])

    assert tracker.finished
    finished = list(itertools.chain.from_iterable(tracker.finished_workunit_chunks))

    process_workunit = next(item for item in finished if item["name"] == "process")
    assert process_workunit is not None
    stdout_digest = process_workunit["artifacts"]["stdout_digest"]
    stderr_digest = process_workunit["artifacts"]["stderr_digest"]

    assert result.stdout == b"stdout output\n"
    assert stderr_digest == EMPTY_FILE_DIGEST
    assert stdout_digest.serialized_bytes_length == len(result.stdout)

    tracker = WorkunitTracker()
    handler = StreamingWorkunitHandler(
        scheduler,
        run_tracker=run_tracker,
        callbacks=[tracker],
        report_interval_seconds=0.01,
        max_workunit_verbosity=LogLevel.DEBUG,
        specs=Specs.empty(),
        options_bootstrapper=create_options_bootstrapper([]),
        allow_async_completion=False,
    )
    stderr_process = Process(
        argv=("/bin/bash", "-c", "1>&2 /bin/echo 'stderr output'"), description="Stderr process"
    )
    with handler:
        result = rule_runner.request(ProcessResult, [stderr_process])

    assert tracker.finished
    finished = list(itertools.chain.from_iterable(tracker.finished_workunit_chunks))
    process_workunit = next(item for item in finished if item["name"] == "process")

    assert process_workunit is not None
    stdout_digest = process_workunit["artifacts"]["stdout_digest"]
    stderr_digest = process_workunit["artifacts"]["stderr_digest"]

    assert result.stderr == b"stderr output\n"
    assert stdout_digest == EMPTY_FILE_DIGEST
    assert stderr_digest.serialized_bytes_length == len(result.stderr)

    assert process_workunit["metadata"]["exit_code"] == 0

    try:
        scheduler.ensure_remote_has_recursive([stdout_digest, stderr_digest])
    except Exception as e:
        # This is the exception message we should expect from invoking ensure_remote_has_recursive()
        # in rust.
        assert str(e) == "Cannot ensure remote has blobs without a remote"

    byte_outputs = scheduler.single_file_digests_to_bytes([stdout_digest, stderr_digest])
    assert byte_outputs[0] == result.stdout
    assert byte_outputs[1] == result.stderr


def test_context_object_on_streaming_workunits(
    rule_runner: RuleRunner, run_tracker: RunTracker
) -> None:
    scheduler = rule_runner.scheduler

    class Callback(WorkunitsCallback):
        @property
        def can_finish_async(self) -> bool:
            return False

        def __call__(self, **kwargs) -> None:
            context = kwargs["context"]
            assert isinstance(context, StreamingWorkunitContext)

            completed_workunits = kwargs["completed_workunits"]
            for workunit in completed_workunits:
                if "artifacts" in workunit and "stdout_digest" in workunit["artifacts"]:
                    digest = workunit["artifacts"]["stdout_digest"]
                    output = context.single_file_digests_to_bytes([digest])
                    assert output == [b"stdout output\n"]

    handler = StreamingWorkunitHandler(
        scheduler,
        run_tracker=run_tracker,
        callbacks=[Callback()],
        report_interval_seconds=0.01,
        max_workunit_verbosity=LogLevel.INFO,
        specs=Specs.empty(),
        options_bootstrapper=create_options_bootstrapper([]),
        allow_async_completion=False,
    )
    stdout_process = Process(
        argv=("/bin/bash", "-c", "/bin/echo 'stdout output'"), description="Stdout process"
    )
    with handler:
        rule_runner.request(ProcessResult, [stdout_process])


def test_streaming_workunits_expanded_specs(run_tracker: RunTracker) -> None:
    rule_runner = RuleRunner(
        target_types=[PythonSourcesGeneratorTarget],
        rules=[
            QueryRule(ProcessResult, (Process,)),
        ],
    )
    rule_runner.set_options(["--backend-packages=pants.backend.python"])
    rule_runner.write_files(
        {
            "src/python/somefiles/BUILD": "python_sources()",
            "src/python/somefiles/a.py": "print('')",
            "src/python/somefiles/b.py": "print('')",
            "src/python/others/BUILD": "python_sources()",
            "src/python/others/a.py": "print('')",
            "src/python/others/b.py": "print('')",
        }
    )
    specs = SpecsParser().parse_specs(
        ["src/python/somefiles::", "src/python/others/b.py"], description_of_origin="tests"
    )

    class Callback(WorkunitsCallback):
        @property
        def can_finish_async(self) -> bool:
            return False

        def __call__(self, **kwargs) -> None:
            context = kwargs["context"]
            assert isinstance(context, StreamingWorkunitContext)

            expanded = context.get_expanded_specs()
            targets = expanded.targets

            assert len(targets.keys()) == 2
            assert targets["src/python/others/b.py"] == [
                TargetInfo(filename="src/python/others/b.py")
            ]
            assert set(targets["src/python/somefiles"]) == {
                TargetInfo(filename="src/python/somefiles/a.py"),
                TargetInfo(filename="src/python/somefiles/b.py"),
            }

    handler = StreamingWorkunitHandler(
        scheduler=rule_runner.scheduler,
        run_tracker=run_tracker,
        callbacks=[Callback()],
        report_interval_seconds=0.01,
        max_workunit_verbosity=LogLevel.INFO,
        specs=specs,
        options_bootstrapper=create_options_bootstrapper(
            ["--backend-packages=pants.backend.python"]
        ),
        allow_async_completion=False,
    )
    stdout_process = Process(
        argv=("/bin/bash", "-c", "/bin/echo 'stdout output'"), description="Stdout process"
    )
    with handler:
        rule_runner.request(ProcessResult, [stdout_process])


@union
class Union:
    pass


class Member(Union):
    pass


def test_union_member_construction(run_tracker: RunTracker) -> None:
    """Use a union member which is a subclass of its @union as a Get input."""

    @rule
    async def output(_: Member) -> str:
        return "yep"

    @rule
    async def for_member() -> str:
        return await Get(str, Member())

    rule_runner = RuleRunner(
        target_types=[],
        rules=[
            UnionRule(Union, Member),
            QueryRule(str, ()),
            output,
            for_member,
        ],
    )

    assert "yep" == rule_runner.request(str, [])


@dataclass(frozen=True)
class FileInput:
    filename: str


@dataclass(frozen=True)
class MergedOutput:
    digest: Digest


class MergeErr(Exception):
    pass


@rule
async def catch_merge_digests_error(file_input: FileInput) -> MergedOutput:
    # Create two separate digests writing different contents to the same file path.
    input_1 = CreateDigest((FileContent(path=file_input.filename, content=b"yes"),))
    input_2 = CreateDigest((FileContent(path=file_input.filename, content=b"no"),))
    digests = await MultiGet(Get(Digest, CreateDigest, input_1), Get(Digest, CreateDigest, input_2))
    try:
        merged = await Get(Digest, MergeDigests(digests))
    except IntrinsicError as e:
        raise MergeErr(f"error merging digests for input {file_input}: {e}")
    return MergedOutput(merged)


def test_catch_intrinsic_error() -> None:
    rule_runner = RuleRunner(
        rules=[catch_merge_digests_error, QueryRule(MergedOutput, (FileInput,))]
    )
    msg = softwrap(
        """\
        error merging digests for input FileInput(filename='some-file.txt'): Can only merge
        Directories with no duplicates, but found 2 duplicate entries in :
        """
    )
    with engine_error(MergeErr, contains=msg):
        rule_runner.request(MergedOutput, (FileInput("some-file.txt"),))
