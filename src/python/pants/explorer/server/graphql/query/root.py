# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import strawberry

from pants.explorer.server.graphql.query.api_types import QueryPluginApiTypesMixin
from pants.explorer.server.graphql.query.backends import QueryBackendsMixin
from pants.explorer.server.graphql.query.rules import QueryRulesMixin
from pants.explorer.server.graphql.query.subsystems import QuerySubsystemsMixin
from pants.explorer.server.graphql.query.targets import QueryTargetsMixin


@strawberry.type
class Query(
    QueryBackendsMixin,
    QueryPluginApiTypesMixin,
    QueryRulesMixin,
    QuerySubsystemsMixin,
    QueryTargetsMixin,
):
    """Access to Pantsbuild data."""
