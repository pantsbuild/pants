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
from pants.backend.project_info.tasks.dependencies import Dependencies
from pants.backend.project_info.tasks.depmap import Depmap
from pants.backend.project_info.tasks.export import Export
from pants.backend.project_info.tasks.filedeps import FileDeps
from pants.backend.project_info.tasks.idea_plugin_gen import IdeaPluginGen
from pants.goal.task_registrar import TaskRegistrar as task


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
        *filter_targets.rules(),
        *list_roots.rules(),
        *list_targets.rules(),
        *source_file_validator.rules(),
    ]
