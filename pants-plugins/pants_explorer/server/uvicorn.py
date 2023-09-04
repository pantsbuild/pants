# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable

from fastapi import FastAPI
from pants_explorer.server.browser import BrowserRequest
from uvicorn import Config, Server  # type: ignore

from pants.base.exiter import ExitCode
from pants.engine.environment import EnvironmentName
from pants.engine.explorer import ExplorerServer, ExplorerServerRequest, RequestState
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.unions import UnionMembership, union

logger = logging.getLogger(__name__)


class UvicornServerRequest(ExplorerServerRequest):
    pass


@dataclass
class UvicornServer:
    app: FastAPI
    config: Config
    request_state: RequestState
    prerun_tasks: list[Callable[[], Any]] = field(default_factory=list)

    def __post_init__(self):
        self.config.callback_notify = self.on_tick

    @classmethod
    def from_request(cls, request: UvicornServerRequest) -> UvicornServer:
        app = FastAPI()
        return cls(
            app=app,
            config=Config(
                app,
                host=request.address,
                port=request.port,
                timeout_notify=0.25,
                log_config=None,
            ),
            request_state=request.request_state,
        )

    def create_server(self) -> ExplorerServer:
        self.server = Server(config=self.config)
        return ExplorerServer(main=self.run)

    async def on_tick(self) -> None:
        if self.request_state.scheduler_session.is_cancelled:
            print()  # Linebreak after the echoed ^C on the terminal.
            logger.info(" => Exiting...")
            self.server.should_exit = True

    def run(self) -> ExitCode:
        logging.info("Starting the Explorer Web UI server...")

        for task in self.prerun_tasks:
            task()

        self.server.run()
        return 0


@union(in_scope_types=[EnvironmentName])
@dataclass(frozen=True)
class UvicornServerSetupRequest:
    server: UvicornServerRequest

    def browser_request(self, protocol: str = "http") -> BrowserRequest:
        server = ":".join((self.server.address, str(self.server.port)))
        return BrowserRequest(protocol, server)


@dataclass(frozen=True)
class UvicornServerSetup:
    callback: Callable[[UvicornServer], None]

    def apply(self, uvicorn: UvicornServer) -> None:
        self.callback(uvicorn)


@rule
async def create_server(
    request: UvicornServerRequest, union_membership: UnionMembership
) -> ExplorerServer:
    uvicorn = UvicornServer.from_request(request)
    setups = await MultiGet(
        Get(UvicornServerSetup, UvicornServerSetupRequest, request_type(request))
        for request_type in union_membership.get(UvicornServerSetupRequest)
    )
    for setup in setups:
        setup.apply(uvicorn)

    return uvicorn.create_server()


def rules():
    return (
        *collect_rules(),
        *ExplorerServerRequest.rules_for_implementation(UvicornServerRequest),
    )
