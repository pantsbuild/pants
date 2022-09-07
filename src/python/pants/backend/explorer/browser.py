# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from dataclasses import dataclass

from pants.core.util_rules.system_binaries import OpenBinary
from pants.engine.environment import EnvironmentName
from pants.engine.explorer import RequestState
from pants.engine.process import Process, ProcessCacheScope, ProcessResult
from pants.engine.rules import QueryRule, collect_rules, rule
from pants.util.logging import LogLevel


@dataclass(frozen=True)
class Browser:
    open_binary: OpenBinary
    protocol: str
    server: str

    def open(self, request_state: RequestState, uri: str = "/") -> ProcessResult | None:
        if not self.open_binary:
            return None

        url = f"{self.protocol}://{self.server}{uri}"
        return request_state.product_request(
            ProcessResult,
            (
                Process(
                    (self.open_binary.path, url),
                    description=f"Open {url} with default web browser.",
                    level=LogLevel.INFO,
                    cache_scope=ProcessCacheScope.PER_SESSION,
                ),
            ),
        )


@dataclass(frozen=True)
class BrowserRequest:
    protocol: str
    server: str


@rule
async def get_browser(request: BrowserRequest, open_binary: OpenBinary) -> Browser:
    return Browser(open_binary, request.protocol, request.server)


def rules():
    return (
        *collect_rules(),
        QueryRule(ProcessResult, (Process, EnvironmentName)),
    )
