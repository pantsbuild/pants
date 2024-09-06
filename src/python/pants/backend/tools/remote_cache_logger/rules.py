# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
import csv
import logging
from typing import Any, Dict, Mapping, Tuple

from pants.engine.internals.scheduler import Workunit
from pants.engine.rules import collect_rules, rule
from pants.engine.streaming_workunit_handler import (
    StreamingWorkunitContext,
    WorkunitsCallback,
    WorkunitsCallbackFactory,
    WorkunitsCallbackFactoryRequest,
)
from pants.engine.unions import UnionRule
from pants.option.option_types import BoolOption, StrOption
from pants.option.subsystem import Subsystem
from pants.util.dirutil import safe_open

logger = logging.getLogger(__name__)


class RemoteCacheLoggerCallback(WorkunitsCallback):
    """Configuration for RemoteCacheLogger."""

    def __init__(self, wulogger: "RemoteCacheLogger"):
        self.wulogger = wulogger
        self._completed_workunits: Dict[str, Mapping[str, Any]] = {}

    @property
    def can_finish_async(self) -> bool:
        return False

    def __call__(
        self,
        *,
        completed_workunits: Tuple[Workunit, ...],
        started_workunits: Tuple[Workunit, ...],
        context: StreamingWorkunitContext,
        finished: bool = False,
        **kwargs: Any,
    ) -> None:
        for wu in completed_workunits:
            if wu["name"] == "remote_cache_read_speculation":
                self._completed_workunits[wu["span_id"]] = {
                    "description": wu["metadata"]["user_metadata"]["request_description"],
                    "action_digest": wu["metadata"]["user_metadata"]["action_digest"],
                    "outcome": wu["metadata"]["user_metadata"]["outcome"],
                    "request": wu["metadata"]["user_metadata"]["request"],
                }
        if finished:
            filepath = f"{self.wulogger.logdir}/{context.run_tracker.run_id}.csv"
            with safe_open(filepath, "w", newline="") as f:
                fieldnames = ["description", "action_digest", "outcome", "request"]
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(self._completed_workunits.values())
                logger.info(f"Wrote log to {filepath}")


class RemoteCacheLoggerCallbackFactoryRequest:
    """A unique request type that is installed to trigger construction of our WorkunitsCallback."""


class RemoteCacheLogger(Subsystem):
    options_scope = "remote-cache-logger"
    help = "Remote Cache Logger subsystem. Useful for debugging remote cache."

    enabled = BoolOption("--enabled", default=False, help="Whether to enable remote cache logging.")
    logdir = StrOption("--logdir", default=".pants.d/workdir", help="Where to write the log to.")


@rule
def construct_callback(
    _: RemoteCacheLoggerCallbackFactoryRequest,
    wulogger: RemoteCacheLogger,
) -> WorkunitsCallbackFactory:
    return WorkunitsCallbackFactory(
        lambda: RemoteCacheLoggerCallback(wulogger) if wulogger.enabled else None
    )


def rules():
    return [
        UnionRule(WorkunitsCallbackFactoryRequest, RemoteCacheLoggerCallbackFactoryRequest),
        *collect_rules(),
    ]
