# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.python.lint import python_format_target, python_lint_target
from pants.backend.python.lint.isort import rules as isort_rules
from pants.backend.python.lint.isort.isort_prep import IsortPrep
from pants.backend.python.lint.isort.isort_run import IsortRun
from pants.goal.task_registrar import TaskRegistrar as task


def rules():
    return (
        *isort_rules.rules(),
        *python_format_target.rules(),
        *python_lint_target.rules(),
    )


def register_goals():
    task(name="isort-prep", action=IsortPrep).install("fmt")
    task(name="isort", action=IsortRun).install("fmt")
