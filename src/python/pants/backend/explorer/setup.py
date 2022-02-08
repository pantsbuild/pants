# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, cast

from pants.backend.explorer.request_state import RequestState
from pants.base.exiter import ExitCode
from pants.engine.rules import QueryRule
from pants.engine.unions import UnionRule, union


@union
@dataclass(frozen=True)
class ExplorerServerRequest:
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
