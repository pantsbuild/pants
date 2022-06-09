# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Iterable, TypeVar, cast

from pants.base.exiter import ExitCode
from pants.build_graph.build_configuration import BuildConfiguration
from pants.engine.internals.scheduler import SchedulerSession
from pants.engine.internals.selectors import Params
from pants.engine.rules import QueryRule
from pants.engine.unions import UnionRule, union
from pants.help.help_info_extracter import AllHelpInfo

T = TypeVar("T")


@union
@dataclass(frozen=True)
class ExplorerServerRequest:
    address: str
    port: int
    request_state: RequestState

    @classmethod
    def rules_for_implementation(cls, impl: type):
        return (
            UnionRule(cls, impl),
            QueryRule(ExplorerServer, (impl,)),
        )


@dataclass(frozen=True)
class ExplorerServer:
    main: Callable[[], ExitCode]

    def run(self) -> ExitCode:
        # Work around a mypy issue with a callable attribute.  Related to
        # https://github.com/python/mypy/issues/6910.  What has me bugged out is why we don't see
        # this issue with `WorkunitsCallbackFactory.callback_factory` too, for instance.
        main = cast("Callable[[], ExitCode]", getattr(self, "main"))
        return main()


@dataclass(frozen=True)
class RequestState:
    all_help_info: AllHelpInfo
    build_configuration: BuildConfiguration
    scheduler_session: SchedulerSession

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
