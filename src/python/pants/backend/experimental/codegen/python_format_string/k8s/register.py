# Copyright 2025 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from pants.backend.codegen.python_format_string.k8s import rules as k8s_rules


def rules():
    return k8s_rules.rules()
