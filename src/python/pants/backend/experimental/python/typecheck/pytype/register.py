# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from pants.backend.python.typecheck.pytype import rules as pytype_rules
from pants.backend.python.typecheck.pytype import skip_field


def rules():
    return (*pytype_rules.rules(), *skip_field.rules())
