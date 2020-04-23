# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

"""Deprecated custom Python lints.

Instead, use the V2 backend `pants.backend.python.lint.flake8`.
"""

from pants.base.deprecated import deprecated_module
from pants.goal.task_registrar import TaskRegistrar as task

from pants.contrib.python.checks.tasks.checkstyle.checkstyle import Checkstyle
from pants.contrib.python.checks.tasks.python_eval import PythonEval

deprecated_module(
    removal_version="1.30.0.dev0",
    hint_message=(
        "The `pants.contrib.python.checks` will no longer be maintained as it has been superseded "
        "by more modern and powerful linters. To prepare, remove the "
        "`pantsbuild.pants.contrib.python.checks` plugin from your "
        "`pants.toml` (or `pants.ini`).\n\nIf you used `lint.pythonstyle`, see "
        "https://github.com/pantsbuild/flake8-pantsbuild#migrating-from-lintpythonstyle-to-flake8 "
        "for a guide on how to migrate to the V2 implementation of Flake8, which offers many more "
        "lints and allows you to easily install additional plugins.\n\nIf you used "
        "`lint.python-eval`, we recommend using MyPy by adding `pantsbuild.pants.contrib.mypy` "
        "to your list of `plugins`."
    ),
)


def register_goals():
    task(name="python-eval", action=PythonEval).install("lint")
    task(name="pythonstyle", action=Checkstyle).install("lint")
