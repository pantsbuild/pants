# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.shell.target_types import rules as target_type_rules
from pants.backend.toml.goals import tailor
from pants.backend.toml.target_types import TomlSourcesGeneratorTarget, TomlSourceTarget


def target_types():
    return [TomlSourceTarget, TomlSourcesGeneratorTarget]


def rules():
    return [*tailor.rules(), *target_type_rules()]
