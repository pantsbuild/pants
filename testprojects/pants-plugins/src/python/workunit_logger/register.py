# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import logging
import time
from dataclasses import dataclass
from typing import Tuple

from pants.engine.internals.scheduler import Workunit
from pants.engine.rules import collect_rules, rule
from pants.engine.streaming_workunit_handler import (
    StreamingWorkunitContext,
    WorkunitsCallback,
    WorkunitsCallbackFactory,
    WorkunitsCallbackFactoryRequest,
)
from pants.engine.unions import UnionRule
from pants.option.subsystem import Subsystem

logger = logging.getLogger(__name__)


FINISHED_SUCCESSFULLY = "$Finished Successfully$"


class WorkunitsLoggerOptions(Subsystem):
    options_scope = "workunit-logger"
    help = """Example plugin that logs workunits to a file."""

    @classmethod
    def register_options(cls, register):
        register("--dest", type=str, help="A filename to log workunits to.")


class WorkunitsLoggerRequest:
    pass


@dataclass(frozen=True)
class WorkunitsLogger(WorkunitsCallback):
    dest: str

    @property
    def can_finish_async(self) -> bool:
        return True

    def __call__(
        self,
        *,
        completed_workunits: Tuple[Workunit, ...],
        finished: bool,
        context: StreamingWorkunitContext,
        **kwargs
    ) -> None:
        with open(self.dest, "a") as dest:
            print(str(completed_workunits), file=dest)
            if finished and context.run_tracker.has_ended():
                # Sleep a little while to ensure that we're finishing asynchronously.
                time.sleep(2)
                print(FINISHED_SUCCESSFULLY, file=dest)


@rule
def construct_workunits_logger_callback(
    _: WorkunitsLoggerRequest,
    opts: WorkunitsLoggerOptions,
) -> WorkunitsCallbackFactory:
    output_file = opts.options.dest
    return WorkunitsCallbackFactory(lambda: WorkunitsLogger(output_file))


def rules():
    return [
        UnionRule(WorkunitsCallbackFactoryRequest, WorkunitsLoggerRequest),
        *collect_rules(),
    ]
