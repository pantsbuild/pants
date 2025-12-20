# Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from pants.backend.experimental.helm.register import rules as helm_rules
from pants.backend.helm.lint.trivy.rules import rules as trivy_helm_rules
from pants.backend.tools.trivy.rules import rules as trivy_rules


def rules():
    return (
        *helm_rules(),
        *trivy_rules(),
        *trivy_helm_rules(),
    )
