# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from pants.option.option_types import BoolOption
from pants.option.subsystem import Subsystem
from pants.util.strutil import softwrap


class GraphQLSubsystem(Subsystem):
    options_scope = "graphql"
    help = "Options for the explorer GraphQL API."

    open_graphiql = BoolOption(
        default=False,
        help=softwrap(
            """
            Open a new web browser tab with GraphiQL.

            GraphiQL is an in-browser tool for writing, validating, and testing GraphQL queries.
            """
        ),
    )
