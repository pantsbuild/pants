# Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from pants.backend.terraform.lint.trivy.rules import rules as trivy_terraform_rules
from pants.backend.tools.trivy.rules import rules as trivy_rules


def rules():
    return (
        # TODO: Register Terraform rules
        *trivy_rules(),
        *trivy_terraform_rules(),
    )
