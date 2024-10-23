# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
"""Information on your project, such as listing the targets in your project."""

from pants.backend.project_info import (
    count_loc,
    dependencies,
    dependents,
    filedeps,
    filter_targets,
    list_roots,
    list_targets,
    paths,
    peek,
    regex_lint,
)


def rules():
    return [
        *count_loc.rules(),
        *dependencies.rules(),
        *dependents.rules(),
        *filedeps.rules(),
        *filter_targets.rules(),
        *list_roots.rules(),
        *list_targets.rules(),
        *paths.rules(),
        *peek.rules(),
        *regex_lint.rules(),
    ]
