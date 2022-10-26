# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.project_info.subsystems import lockfile_diff


def rules():
    return (*lockfile_diff.rules(),)
