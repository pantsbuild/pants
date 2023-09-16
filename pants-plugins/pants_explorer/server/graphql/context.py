# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from dataclasses import dataclass
from typing import cast

from pants_explorer.server.uvicorn import UvicornServer
from strawberry.types import Info

from pants.engine.explorer import RequestState


@dataclass(frozen=True)
class GraphQLContext:
    uvicorn: UvicornServer

    def create_request_context(self) -> dict[str, RequestState]:
        return dict(pants_request_state=self.uvicorn.request_state)

    @staticmethod
    def request_state_from_info(info: Info) -> RequestState:
        assert info.context is not None
        request_state = cast("RequestState | None", info.context.get("pants_request_state"))
        assert request_state is not None
        return request_state
