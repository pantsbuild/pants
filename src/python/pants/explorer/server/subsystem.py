# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
from typing import Callable

from starlette.middleware.cors import CORSMiddleware

from pants.engine.rules import collect_rules, rule
from pants.engine.unions import UnionRule
from pants.explorer.server.uvicorn import (
    UvicornServer,
    UvicornServerSetup,
    UvicornServerSetupRequest,
)
from pants.option.option_types import BoolOption, StrListOption
from pants.option.subsystem import Subsystem
from pants.util.strutil import softwrap

logger = logging.getLogger(__name__)


class UvicornSubsystem(Subsystem):
    options_scope = "uvicorn"
    help = softwrap(
        """
        Uvicorn server options used by the Explorer backend.

        CORS
        ----

        The CORS options are for the FastAPI middleware, which is disabled by default but have
        permissive defaults when enabled.

        See FastAPI docs for more info: https://fastapi.tiangolo.com/tutorial/cors/
        """
    )
    cors = BoolOption(default=False, help="Enable CORS support for the uvicorn server.")
    cors_allow_origins = StrListOption(default=["*"], help="Allow origins.")
    cors_allow_methods = StrListOption(default=["*"], help="Allow methods.")
    cors_allow_headers = StrListOption(default=["*"], help="Allow headers.")
    cors_allow_credentials = BoolOption(default=True, help="Allow credentials.")


class BaseUvicornServerSetupRequest(UvicornServerSetupRequest):
    pass


def uvicorn_setup(uvicorn: UvicornSubsystem) -> Callable[[UvicornServer], None]:
    def setup(server: UvicornServer) -> None:
        if not uvicorn.cors:
            logger.info("CORS disabled")
        else:
            cors = dict(
                allow_origins=uvicorn.cors_allow_origins,
                allow_methods=uvicorn.cors_allow_methods,
                allow_headers=uvicorn.cors_allow_headers,
                allow_credentials=uvicorn.cors_allow_credentials,
            )
            logger.info(f"CORS enabled: {', '.join(f'{k}:{v}' for k, v in cors.items())}")
            server.app.add_middleware(CORSMiddleware, **cors)

    return setup


@rule
async def get_uvicorn_setup(
    request: BaseUvicornServerSetupRequest, uvicorn: UvicornSubsystem
) -> UvicornServerSetup:
    return UvicornServerSetup(uvicorn_setup(uvicorn))


def rules():
    return (
        *collect_rules(),
        UnionRule(UvicornServerSetupRequest, BaseUvicornServerSetupRequest),
    )
