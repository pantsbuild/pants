# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

"""Linter for Java (deprecated).

See https://errorprone.info.
"""

from pants.base.deprecated import _deprecated_contrib_plugin
from pants.goal.task_registrar import TaskRegistrar as task

from pants.contrib.errorprone.tasks.errorprone import ErrorProne

_deprecated_contrib_plugin("pantsbuild.pants.contrib.errorprone")


def register_goals():
    task(name="errorprone", action=ErrorProne).install("compile")
