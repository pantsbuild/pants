# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from typing import cast

from pants.base.deprecated import resolve_conflicting_options
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
            "--global",
            type=list,
            member_type=str,
            advanced=True,
            default=[],
            # NB: `global` is a python keyword.
            dest="global_addresses",
            removal_version="2.10.0.dev0",
            removal_hint="Use `--plugins-global`, which behaves the same.",
            help=(
                "A list of addresses of `scalac_plugin` targets which should be used for "
                "compilation of all Scala targets in a build."
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
            "--lockfile",
            type=str,
            default="3rdparty/jvm/global_scalac_plugins.lockfile",
            advanced=True,
            removal_version="2.10.0.dev0",
            removal_hint="Use `--plugins-global-lockfile`, which behaves the same.",
            help=("The filename of a lockfile for global plugins."),
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
        plugins_global = resolve_conflicting_options(
            old_option="global_addresses",
            new_option="plugins_global",
            old_scope="scalac",
            new_scope="scalac",
            old_container=self.options,
            new_container=self.options,
        )
        return cast("list[str]", plugins_global)

    @property
    def plugins_global_lockfile(self) -> str:
        plugins_global_lockfile = resolve_conflicting_options(
            old_option="lockfile",
            new_option="plugins_global_lockfile",
            old_scope="scalac",
            new_scope="scalac",
            old_container=self.options,
            new_container=self.options,
        )
        return cast(str, plugins_global_lockfile)
