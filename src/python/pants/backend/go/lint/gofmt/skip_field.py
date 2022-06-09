# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.go.target_types import GoPackageTarget
from pants.engine.target import BoolField


class SkipGofmtField(BoolField):
    alias = "skip_gofmt"
    default = False
    help = "If true, don't run gofmt on this package."


def rules():
    return [GoPackageTarget.register_plugin_field(SkipGofmtField)]
