# Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from pants.backend.helm.lint.trivy.rules import rules as trivy_rules


def rules():
    return trivy_rules()
