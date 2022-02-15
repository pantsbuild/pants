# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.helm.codegen.helmdocs.rules import rules as helmdocs_rules


def target_types():
    return []


def rules():
    return helmdocs_rules()
