# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from pants.backend.toml.target_types import TomlSourcesGeneratorTarget, TomlSourceTarget
from pants.engine.target import BoolField


class SkipTaploField(BoolField):
    alias = "skip_taplo"
    default = False
    help = "If true, don't run taplo on this target's code."


def rules():
    return [
        TomlSourceTarget.register_plugin_field(SkipTaploField),
        TomlSourcesGeneratorTarget.register_plugin_field(SkipTaploField),
    ]
