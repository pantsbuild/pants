# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.core.target_types import FilesSources
from pants.engine.target import COMMON_TARGET_FIELDS, Target


class CargoProject(Target):
    alias = 'cargo_project'
    core_fields = (*COMMON_TARGET_FIELDS, FilesSources)
