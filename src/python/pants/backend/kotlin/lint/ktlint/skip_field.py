# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.kotlin.target_types import KotlinSourcesGeneratorTarget, KotlinSourceTarget
from pants.engine.target import BoolField


class SkipKtlintField(BoolField):
    alias = "skip_ktlint"
    default = False
    help = "If true, don't run Ktlint on this target's code."


def rules():
    return [
        KotlinSourceTarget.register_plugin_field(SkipKtlintField),
        KotlinSourcesGeneratorTarget.register_plugin_field(SkipKtlintField),
    ]
