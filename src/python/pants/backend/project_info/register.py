# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

"""Information on your project, such as listing the targets in your project."""

from pants.backend.project_info import (
    cloc,
    dependees,
    dependencies,
    filedeps,
    list_roots,
    list_targets,
    list_targets_old,
    source_file_validator,
)
from pants.backend.project_info.tasks.dependencies import Dependencies
from pants.backend.project_info.tasks.depmap import Depmap
from pants.backend.project_info.tasks.export import Export
from pants.backend.project_info.tasks.filedeps import FileDeps
from pants.backend.project_info.tasks.idea_plugin_gen import IdeaPluginGen
from pants.goal.task_registrar import TaskRegistrar as task
from pants.option.options_bootstrapper import is_v2_exclusive


def register_goals():
    task(name="idea-plugin", action=IdeaPluginGen).install()
    task(name="export", action=Export).install()
    task(name="depmap", action=Depmap).install()
    task(name="dependencies", action=Dependencies).install()
    task(name="filedeps", action=FileDeps).install("filedeps")


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
