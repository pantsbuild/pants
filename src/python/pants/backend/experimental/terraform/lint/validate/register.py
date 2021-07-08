# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.terraform.lint.validate.validate import rules as validate_rules


def rules():
    return [
        *validate_rules(),
    ]
