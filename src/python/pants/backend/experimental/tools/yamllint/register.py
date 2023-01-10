# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from pants.backend.tools.yamllint.rules import rules as yamllint_rules


def rules():
    return [*yamllint_rules()]
