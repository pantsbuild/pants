# Copyright 2026 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import datetime
import logging
from contextlib import contextmanager
from typing import Generator

from pants.backend.observability.opentelemetry.processor import (
    IncompleteWorkunit,
    Processor,
    ProcessorContext,
    Workunit,
)

logger = logging.getLogger(__name__)


class ExceptionLoggingProcessor(Processor):
    def __init__(self, processor: Processor, *, name: str) -> None:
        self._processor = processor
        self._name = name
        self._exception_count = 0

    @contextmanager
    def _wrapper(self) -> Generator[None]:
        try:
            yield
        except Exception as ex:
            logger.debug(
                f"An exception occurred while processing a workunit in the {self._name} workunit tracing handler: {ex}",
                exc_info=True,
            )
            if self._exception_count == 0:
                logger.warning(
                    f"Ignored an exception from the {self._name} workunit tracing handler. These exceptions will be logged "
                    "at DEBUG level. No further warnings will be logged."
                )
            self._exception_count += 1

    def initialize(self) -> None:
        with self._wrapper():
            self._processor.initialize()

    def start_workunit(self, workunit: IncompleteWorkunit, *, context: ProcessorContext) -> None:
        with self._wrapper():
            self._processor.start_workunit(workunit=workunit, context=context)

    def complete_workunit(self, workunit: Workunit, *, context: ProcessorContext) -> None:
        with self._wrapper():
            self._processor.complete_workunit(workunit=workunit, context=context)

    def finish(
        self, timeout: datetime.timedelta | None = None, *, context: ProcessorContext
    ) -> None:
        with self._wrapper():
            self._processor.finish(timeout=timeout, context=context)
        if self._exception_count > 1:
            logger.warning(
                f"Ignored {self._exception_count} exceptions from the {self._name} workunit tracing handler."
            )
