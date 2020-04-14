# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

"""Linter for Java (deprecated).

See http://findbugs.sourceforge.net.
"""
from pants.base.deprecated import _deprecated_contrib_plugin
from pants.goal.task_registrar import TaskRegistrar as task

from pants.contrib.findbugs.tasks.findbugs import FindBugs

_deprecated_contrib_plugin("pantsbuild.pants.contrib.findbugs")


def register_goals():
    task(name="findbugs", action=FindBugs).install("compile")
