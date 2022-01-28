# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from typing import cast

from pants.core.goals.generate_lockfiles import DEFAULT_TOOL_LOCKFILE
from pants.option.custom_types import shell_str
from pants.option.subsystem import Subsystem


class Scalac(Subsystem):
    options_scope = "scalac"
    help = "The Scala compiler."

    default_plugins_lockfile_path = (
        "src/python/pants/backend/scala/subsystems/scalac_plugins.default.lockfile.txt"
    )
    default_plugins_lockfile_resource = (
        "pants.backend.scala.subsystems",
        "scalac_plugins.default.lockfile.txt",
    )

    @classmethod
    def register_options(cls, register):
        super().register_options(register)
        register(
            "--args",
            type=list,
            member_type=shell_str,
            default=[],
            help=(
                "Global `scalac` compiler flags, e.g. "
                f"`--{cls.options_scope}-args='-encoding UTF-8'`."
            ),
        )
        register(
            "--plugins-global",
            type=list,
            member_type=str,
            advanced=True,
            default=[],
            help=(
                "A list of addresses of `scalac_plugin` targets which should be used for "
                "compilation of all Scala targets in a build.\n\nIf you set this, you must also "
                "set `[scalac].plugins_global_lockfile`."
            ),
        )
        register(
            "--plugins-global-lockfile",
            type=str,
            default=DEFAULT_TOOL_LOCKFILE,
            advanced=True,
            help=(
                "The filename of the lockfile for global plugins. You must set this option to a "
                "file path, e.g. '3rdparty/jvm/global_scalac_plugins.lock', if you set "
                "`[scalac].plugins_global`."
            ),
        )

    @property
    def args(self) -> list[str]:
        return cast("list[str]", self.options.args)

    @property
    def plugins_global(self) -> list[str]:
        return cast("list[str]", self.options.plugins_global)

    @property
    def plugins_global_lockfile(self) -> str:
        return cast(str, self.options.plugins_global_lockfile)
