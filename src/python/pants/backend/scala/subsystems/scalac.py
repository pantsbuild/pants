# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from typing import cast

from pants.option.custom_types import shell_str
from pants.option.subsystem import Subsystem


class Scalac(Subsystem):
    options_scope = "scalac"
    help = "The Scala compiler."

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
                "compilation of all Scala targets in a build."
            ),
        )
        register(
            "--plugins-global-lockfile",
            type=str,
            default="3rdparty/jvm/global_scalac_plugins.lock",
            advanced=True,
            help=("The filename of a lockfile for global plugins."),
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
