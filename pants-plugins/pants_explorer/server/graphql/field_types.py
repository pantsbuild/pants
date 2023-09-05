# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import json
from typing import NewType

import strawberry

JSONScalar = strawberry.scalar(
    NewType("JSONScalar", object),
    serialize=lambda v: v,
    parse_value=lambda v: json.loads(v),
    description="The GenericScalar scalar type represents a generic GraphQL scalar value.",
)
