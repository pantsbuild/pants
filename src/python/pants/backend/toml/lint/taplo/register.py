# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.toml.lint.taplo import skip_field
from pants.backend.toml.lint.taplo.rules import rules as taplo_rules


def rules():
    return [*taplo_rules(), *skip_field.rules()]
