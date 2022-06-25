# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.visibility import validate
from pants.engine.target import Target


def rules():
    return (
        *validate.rules(),
        Target.register_plugin_field(validate.VisibilityField),
    )
