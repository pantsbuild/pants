# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

"""Information on your project, such as listing the targets in your project."""

from pants.option.options_bootstrapper import is_v2_exclusive
from pants.project_info import (
    cloc,
    dependees,
    dependencies,
    filedeps,
    list_roots,
    list_targets,
    list_targets_old,
    source_file_validator,
)


def rules():
    return [
        *cloc.rules(),
        *dependees.rules(),
        *dependencies.rules(),
        *filedeps.rules(),
        *list_roots.rules(),
        *list_targets.rules(),
        *(list_targets_old.rules() if not is_v2_exclusive else ()),
        *source_file_validator.rules(),
    ]
