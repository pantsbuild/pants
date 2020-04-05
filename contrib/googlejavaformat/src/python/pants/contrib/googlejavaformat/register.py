# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

"""Autoformatter for Java to follow Google's Java Style guide.

See https://github.com/google/google-java-format.
"""

from pants.goal.task_registrar import TaskRegistrar as task

from pants.contrib.googlejavaformat.googlejavaformat import (
    GoogleJavaFormatLintTask,
    GoogleJavaFormatTask,
)


def register_goals():
    task(name="google-java-format", action=GoogleJavaFormatTask).install("fmt")
    task(name="google-java-format", action=GoogleJavaFormatLintTask).install("lint")
