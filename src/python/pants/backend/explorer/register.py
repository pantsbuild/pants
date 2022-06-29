# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from pants.backend.explorer import browser
from pants.backend.explorer import rules as explorer
from pants.backend.explorer.graphql import rules as graphql
from pants.backend.explorer.server import uvicorn


def rules():
    return (
        *browser.rules(),
        *explorer.rules(),
        *graphql.rules(),
        *uvicorn.rules(),
    )
