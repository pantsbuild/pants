# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

"""Information on your project, such as listing the targets in your project."""

from pants.backend.project_info import (
    cloc,
    dependees,
    dependencies,
    filedeps,
    filter_targets,
    list_roots,
    list_targets,
    source_file_validator,
)


def rules():
    return [
        *cloc.rules(),
        *dependees.rules(),
        *dependencies.rules(),
        *filedeps.rules(),
        *filter_targets.rules(),
        *list_roots.rules(),
        *list_targets.rules(),
        *source_file_validator.rules(),
    ]
