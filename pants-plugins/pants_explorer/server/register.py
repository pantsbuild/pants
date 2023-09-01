# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from pants_explorer.server import browser, uvicorn
from pants_explorer.server.graphql import rules as graphql


def rules():
    return (
        *browser.rules(),
        *graphql.rules(),
        *uvicorn.rules(),
    )
