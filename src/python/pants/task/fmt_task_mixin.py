# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from typing import cast

from pants.subsystem.subsystem import Subsystem


class FmtTaskMixin:
    """A mixin to combine with code formatting tasks."""

    target_filtering_enabled = True

    @property
    def act_transitively(self):
        return False

    def determine_if_skipped(self, *, formatter_subsystem: Subsystem) -> bool:
        # TODO: generalize this to work with every formatter, not only scalafix. When doing this,
        # change the `help` description in `fmt.py`.
        # TODO: expand this to `--lint-only`.
        skipped = cast(bool, formatter_subsystem.options.skip)
        only = self.get_options().only  # type: ignore
        is_scalafix = self.__class__.__name__.startswith("ScalaFix")

        if only is not None and only != "scalafix":
            raise ValueError(
                "Invalid value for `--fmt-only`. It must be `scalafix` or not be set at all."
            )
        if is_scalafix and only == "scalafix" and skipped:
            raise ValueError(
                f"Invalid flag combination. You cannot both set `--fmt-only=scalafix` and "
                f"`--scalafix-skip`.",
            )

        if only == "scalafix" and not is_scalafix:
            return True
        return skipped
