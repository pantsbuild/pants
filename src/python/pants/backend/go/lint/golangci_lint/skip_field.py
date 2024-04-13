# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.go.target_types import GoPackageTarget
from pants.engine.target import BoolField


class SkipGolangciLintField(BoolField):
    alias = "skip_golangci_lint"
    default = False
    help = "If true, don't run `golangci-lint` on this target's code."


def rules():
    return [GoPackageTarget.register_plugin_field(SkipGolangciLintField)]
