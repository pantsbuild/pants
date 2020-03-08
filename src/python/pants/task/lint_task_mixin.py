# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).


class LintTaskMixin:
    """A mixin to combine with lint tasks."""

    target_filtering_enabled = True

    @property
    def act_transitively(self):
        return False
