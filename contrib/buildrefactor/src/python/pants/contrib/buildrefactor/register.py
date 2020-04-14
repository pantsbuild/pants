# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

"""Adds the `buildozer` and `meta-rename` goals to automate changes to BUILD files."""

from pants.goal.task_registrar import TaskRegistrar as task

from pants.contrib.buildrefactor.buildozer import Buildozer
from pants.contrib.buildrefactor.meta_rename import MetaRename


def register_goals():
    task(name="buildozer", action=Buildozer).install("buildozer")
    task(name="meta-rename", action=MetaRename).install("meta-rename")
