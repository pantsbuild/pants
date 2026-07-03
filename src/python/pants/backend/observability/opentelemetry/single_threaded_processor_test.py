# Copyright 2026 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import datetime
import queue
from collections.abc import Mapping

from pants.backend.observability.opentelemetry.processor import (
    IncompleteWorkunit,
    Level,
    Processor,
    ProcessorContext,
    Workunit,
)
from pants.backend.observability.opentelemetry.single_threaded_processor import (
    SingleThreadedProcessor,
)
from pants.util.frozendict import FrozenDict


class CapturingProcessor(Processor):
    def __init__(self) -> None:
        self.initialize_called = False
        self.started_workunits: queue.Queue[IncompleteWorkunit] = queue.Queue()
        self.completed_workunits: queue.Queue[Workunit] = queue.Queue()
        self.finish_called = False

    def initialize(self) -> None:
        self.initialize_called = True

    def start_workunit(self, workunit: IncompleteWorkunit, *, context: ProcessorContext) -> None:
        self.started_workunits.put_nowait(workunit)

    def complete_workunit(self, workunit: Workunit, *, context: ProcessorContext) -> None:
        self.completed_workunits.put_nowait(workunit)

    def finish(
        self, timeout: datetime.timedelta | None = None, *, context: ProcessorContext
    ) -> None:
        self.finish_called = True


class MockProcessorContext(ProcessorContext):
    def get_metrics(self) -> Mapping[str, int]:
        return {}


def test_single_threaded_processor_roundtrip() -> None:
    context = MockProcessorContext()
    processor = CapturingProcessor()
    stp_processor = SingleThreadedProcessor(processor)

    stp_processor.initialize()
    assert processor.initialize_called

    start_time = datetime.datetime.now(datetime.UTC)
    incomplete_workunit = IncompleteWorkunit(
        name="test-span",
        span_id="SOME_SPAN_ID",
        parent_ids=("A_PARENT_SPAN_ID",),
        level=Level.INFO,
        description="This is where the span is described.",
        start_time=start_time,
    )
    stp_processor.start_workunit(workunit=incomplete_workunit, context=context)
    actual_incomplete_workunit = processor.started_workunits.get(timeout=0.250)
    assert actual_incomplete_workunit == incomplete_workunit

    start_time = datetime.datetime.now(datetime.UTC)
    workunit = Workunit(
        name=incomplete_workunit.name,
        span_id=incomplete_workunit.span_id,
        parent_ids=incomplete_workunit.parent_ids,
        level=incomplete_workunit.level,
        description=incomplete_workunit.description,
        start_time=incomplete_workunit.start_time,
        end_time=incomplete_workunit.start_time + datetime.timedelta(milliseconds=100),
        metadata=FrozenDict(),
    )
    stp_processor.complete_workunit(workunit=workunit, context=context)
    actual_workunit = processor.completed_workunits.get(timeout=0.250)
    assert actual_workunit == workunit

    stp_processor.finish(context=context)
    assert processor.finish_called
