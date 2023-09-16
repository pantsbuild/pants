# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import strawberry
from pants_explorer.server.graphql.query.rules import QueryRulesMixin
from pants_explorer.server.graphql.query.targets import QueryTargetsMixin


@strawberry.type
class Query(QueryRulesMixin, QueryTargetsMixin):
    """Access to Pantsbuild data."""
