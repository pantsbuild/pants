# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from pants.option.option_types import BoolOption
from pants.option.subsystem import Subsystem


class OpenApiSubsystem(Subsystem):
    options_scope = "openapi"
    name = "openapi"
    help = "The OpenAPI Specification (https://swagger.io/specification/)."

    tailor_targets = BoolOption(
        default=True,
        help="If true, add `openapi_documents` and `openapi_sources` targets with the `tailor` goal.",
        advanced=True,
    )
