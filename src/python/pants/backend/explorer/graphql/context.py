# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from dataclasses import dataclass
from typing import cast

from strawberry.types import Info

from pants.backend.explorer.server.uvicorn import UvicornServer
from pants.engine.explorer import RequestState


@dataclass(frozen=True)
class GraphQLContext:
    uvicorn: UvicornServer

    def create_request_context(self) -> dict[str, RequestState]:
        return dict(pants_request_state=self.uvicorn.request_state)

    @staticmethod
    def request_state_from_info(info: Info) -> RequestState:
        return cast(RequestState, info.context["pants_request_state"])
