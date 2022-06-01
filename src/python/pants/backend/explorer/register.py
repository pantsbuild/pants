# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from pants.backend.explorer.graphql.rules import rules as graphql_rules
from pants.backend.explorer.rules import rules as explorer_rules
from pants.backend.explorer.server import uvicorn


def rules():
    return (
        *explorer_rules(),
        *graphql_rules(),
        *uvicorn.rules(),
    )
