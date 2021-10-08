# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.go.target_types import GoInternalPackageTarget
from pants.engine.target import BoolField


class SkipGofmtField(BoolField):
    alias = "skip_gofmt"
    default = False
    help = "If true, don't run gofmt on this target's code."


def rules():
    return [GoInternalPackageTarget.register_plugin_field(SkipGofmtField)]
