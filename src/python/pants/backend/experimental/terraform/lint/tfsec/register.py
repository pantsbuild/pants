# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from pants.backend.terraform.lint.tfsec.rules import rules as tfsec_rules


def rules():
    return tfsec_rules()
