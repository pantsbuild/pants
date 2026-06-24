# Copyright 2026 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import datetime
import logging
from collections import defaultdict
from collections.abc import Mapping

import pytest

from pants.backend.observability.opentelemetry.exception_logging_processor import (
    ExceptionLoggingProcessor,
)
from pants.backend.observability.opentelemetry.processor import (
    IncompleteWorkunit,
    Level,
    Processor,
    ProcessorContext,
    Workunit,
)
from pants.util.frozendict import FrozenDict


class AlwaysRaisesExceptionProcessor(Processor):
    def initialize(self) -> None:
        raise ValueError("initialize")

    def start_workunit(self, workunit: IncompleteWorkunit, *, context: ProcessorContext) -> None:
        raise ValueError("start_workunit")

    def complete_workunit(self, workunit: Workunit, *, context: ProcessorContext) -> None:
        raise ValueError("complete_workunit")

    def finish(
        self, timeout: datetime.timedelta | None = None, *, context: ProcessorContext
    ) -> None:
        raise ValueError("finish")


class MockProcessorContext(ProcessorContext):
    def get_metrics(self) -> Mapping[str, int]:
        return {}


@pytest.fixture
def incomplete_workunit() -> IncompleteWorkunit:
    start_time = datetime.datetime.now(datetime.UTC)
    return IncompleteWorkunit(
        name="test-span",
        span_id="SOME_SPAN_ID",
        parent_ids=("A_PARENT_SPAN_ID",),
        level=Level.INFO,
        description="This is where the span is described.",
        start_time=start_time,
    )


@pytest.fixture
def workunit(incomplete_workunit: IncompleteWorkunit) -> Workunit:
    return Workunit(
        name=incomplete_workunit.name,
        span_id=incomplete_workunit.span_id,
        parent_ids=incomplete_workunit.parent_ids,
        level=incomplete_workunit.level,
        description=incomplete_workunit.description,
        start_time=incomplete_workunit.start_time,
        end_time=incomplete_workunit.start_time + datetime.timedelta(milliseconds=100),
        metadata=FrozenDict(),
    )


def test_exception_logging_proessor(
    incomplete_workunit: IncompleteWorkunit, workunit: Workunit, caplog
) -> None:
    processor = ExceptionLoggingProcessor(AlwaysRaisesExceptionProcessor(), name="test")
    context = MockProcessorContext()

    assert len(caplog.record_tuples) == 0
    processor.initialize()
    assert len(caplog.record_tuples) == 1
    assert caplog.record_tuples[0][1] == logging.WARNING
    assert caplog.record_tuples[0][2] == (
        "Ignored an exception from the test workunit tracing handler. These exceptions will be logged "
        "at DEBUG level. No further warnings will be logged."
    )

    caplog.clear()
    processor.start_workunit(workunit=incomplete_workunit, context=context)
    assert len(caplog.record_tuples) == 0

    caplog.clear()
    processor.complete_workunit(workunit=workunit, context=context)
    assert len(caplog.record_tuples) == 0

    caplog.clear()
    processor.finish(context=context)
    assert len(caplog.record_tuples) == 1
    assert caplog.record_tuples[0][1] == logging.WARNING
    assert (
        caplog.record_tuples[0][2] == "Ignored 4 exceptions from the test workunit tracing handler."
    )

    assert processor._exception_count == 4


def test_exceptions_logged_at_debug_level(
    incomplete_workunit: IncompleteWorkunit, workunit: Workunit, caplog
) -> None:
    """With logging level set to DEBUG, exceptions should now be logged at
    DEBUG level."""

    processor = ExceptionLoggingProcessor(AlwaysRaisesExceptionProcessor(), name="test")
    context = MockProcessorContext()

    with caplog.at_level(logging.DEBUG):
        processor.initialize()
        processor.start_workunit(workunit=incomplete_workunit, context=context)
        processor.complete_workunit(workunit=workunit, context=context)
        processor.finish(context=context)

    assert len(caplog.record_tuples) == 6
    log_level_counts: dict[int, int] = defaultdict(int)
    for record in caplog.record_tuples:
        log_level_counts[record[1]] += 1

    assert log_level_counts[logging.WARNING] == 2
    assert log_level_counts[logging.DEBUG] == 4
