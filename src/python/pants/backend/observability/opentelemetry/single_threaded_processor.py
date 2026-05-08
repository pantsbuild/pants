# Copyright 2026 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import datetime
import logging
import queue
from dataclasses import dataclass
from enum import Enum
from threading import Event, Thread

from pants.backend.observability.opentelemetry.processor import (
    IncompleteWorkunit,
    Processor,
    ProcessorContext,
    Workunit,
)

logger = logging.getLogger(__name__)


class _MessageType(Enum):
    START_WORKUNIT = "start_workunit"
    COMPLETE_WORKUNIT = "complete_workunit"
    FINISH = "finish"


@dataclass
class _FinishDetails:
    timeout: datetime.timedelta | None
    context: ProcessorContext


class SingleThreadedProcessor(Processor):
    """This is a `Processor` implementation which pushes all received workunits
    onto a queue for processing on a separate thread.

    This is useful for moving workunit operations off the engine's
    thread. Also, it allows working around any concurrency issues in an
    underlying `Processor` implementation since all operations will
    occur on a single, separate thread.
    """

    def __init__(self, processor: Processor) -> None:
        self._processor = processor

        self._initialize_completed_event = Event()
        self._finish_completed_event = Event()

        self._queue: queue.Queue[
            tuple[
                _MessageType,
                Workunit | IncompleteWorkunit | _FinishDetails,
                ProcessorContext,
            ]
        ] = queue.Queue()

        self._thread = Thread(target=self._processing_loop)
        self._thread.daemon = True

    def _handle_message(
        self,
        msg: tuple[_MessageType, Workunit | IncompleteWorkunit | _FinishDetails, ProcessorContext],
    ) -> _FinishDetails | None:
        """Processes messages.

        Returns a `_FinishDetails` to use for shutdown if the finish
        message was received, else None.
        """
        msg_type: _MessageType = msg[0]
        if msg_type == _MessageType.START_WORKUNIT:
            incomplete_workunit = msg[1]
            assert isinstance(incomplete_workunit, IncompleteWorkunit)
            self._processor.start_workunit(workunit=incomplete_workunit, context=msg[2])
            return None
        elif msg_type == _MessageType.COMPLETE_WORKUNIT:
            workunit = msg[1]
            assert isinstance(workunit, Workunit)
            self._processor.complete_workunit(workunit=workunit, context=msg[2])
            return None
        elif msg_type == _MessageType.FINISH:
            # Finish signalled. Let caller know what context to use for it.
            finish_details = msg[1]
            assert isinstance(finish_details, _FinishDetails)
            return finish_details
        else:
            raise AssertionError("Received unknown message type in SingleThreadedProcessor.")

    def _processing_loop(self) -> None:
        self._processor.initialize()
        self._initialize_completed_event.set()

        finish_details: _FinishDetails | None
        while msg := self._queue.get():
            finish_details = self._handle_message(msg)
            if finish_details is not None:
                break

        if self._queue.qsize() > 0:
            logger.warning(
                "Completion of workunit export was signalled before all workunits in flight were processed!"
            )

        self._processor.finish(timeout=finish_details.timeout, context=finish_details.context)
        self._finish_completed_event.set()

    def initialize(self) -> None:
        self._thread.start()
        if not self._initialize_completed_event.wait(5.0):
            raise RuntimeError("Work unit processor failed to report initialization.")

    def start_workunit(self, workunit: IncompleteWorkunit, *, context: ProcessorContext) -> None:
        self._queue.put_nowait((_MessageType.START_WORKUNIT, workunit, context))

    def complete_workunit(self, workunit: Workunit, *, context: ProcessorContext) -> None:
        self._queue.put_nowait((_MessageType.COMPLETE_WORKUNIT, workunit, context))

    def finish(
        self, timeout: datetime.timedelta | None = None, *, context: ProcessorContext
    ) -> None:
        self._queue.put_nowait(
            (_MessageType.FINISH, _FinishDetails(timeout=timeout, context=context), context)
        )
        timeout_seconds_opt = timeout.total_seconds() if timeout is not None else None
        if not self._finish_completed_event.wait(timeout_seconds_opt):
            raise RuntimeError("Work unit processor failed to report completion.")
        self._thread.join(timeout=timeout_seconds_opt)
