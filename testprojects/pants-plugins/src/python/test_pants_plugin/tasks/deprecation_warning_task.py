# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.base.deprecated import warn_or_error
from pants.task.task import Task


class DeprecationWarningTask(Task):
    """Make a deprecation warning so that warning filters can be integration tested."""

    def execute(self):
        warn_or_error(
            removal_version="999.999.9.dev9",
            deprecated_entity_description="This is a test warning!",
        )
