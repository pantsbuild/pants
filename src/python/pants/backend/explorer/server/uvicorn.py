# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from fastapi import FastAPI
from uvicorn import Config, Server  # type: ignore

from pants.base.exiter import ExitCode
from pants.engine.explorer import ExplorerServer, ExplorerServerRequest, RequestState
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.unions import UnionMembership, union


class UvicornServerRequest(ExplorerServerRequest):
    pass


class UvicornServer:
    def __init__(self, request_state: RequestState):
        self.request_state = request_state
        self.app = FastAPI()
        self.config = Config(
            self.app, callback_notify=self.on_tick, timeout_notify=0.25, log_config=None
        )

    def create_server(self) -> ExplorerServer:
        self.server = Server(config=self.config)
        return ExplorerServer(main=self.run)

    async def on_tick(self) -> None:
        if self.request_state.scheduler_session.is_cancelled:
            print(" => Exiting...")
            self.server.should_exit = True

    def run(self) -> ExitCode:
        print("Starting the Explorer Web UI server...")
        self.server.run()
        return 0


@union
class UvicornServerSetupRequest:
    pass


@dataclass(frozen=True)
class UvicornServerSetup:
    callback: Callable[[UvicornServer], None]

    def apply(self, uvicorn: UvicornServer) -> None:
        self.callback(uvicorn)


@rule
async def create_server(
    request: UvicornServerRequest, union_membership: UnionMembership
) -> ExplorerServer:
    uvicorn = UvicornServer(request.request_state)
    setups = await MultiGet(
        Get(UvicornServerSetup, UvicornServerSetupRequest, request_type())
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
