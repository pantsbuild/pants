# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, TypeVar, cast

from strawberry.types import Info

from pants.build_graph.build_configuration import BuildConfiguration
from pants.engine.internals.scheduler import SchedulerSession
from pants.engine.internals.selectors import Params

T = TypeVar("T")


@dataclass(frozen=True)
class RequestState:
    build_configuration: BuildConfiguration
    scheduler_session: SchedulerSession

    @staticmethod
    def from_info(info: Info) -> RequestState:
        return cast(RequestState, info.context["pants_request_state"])

    def context_getter(self) -> dict[str, RequestState]:
        return dict(pants_request_state=self)

    def product_request(
        self,
        product: type[T],
        subjects: Iterable[Any] = (),
        poll: bool = False,
        timeout: float | None = None,
    ) -> T:
        result = self.scheduler_session.product_request(
            product,
            [Params(*subjects)],
            poll=poll,
            timeout=timeout,
        )
        assert len(result) == 1
        return cast(T, result[0])
