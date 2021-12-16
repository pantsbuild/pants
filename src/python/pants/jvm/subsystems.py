# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from typing import cast

from pants.option.subsystem import Subsystem


class JvmSubsystem(Subsystem):
    options_scope = "jvm"
    help = "Options for general JVM functionality."

    @classmethod
    def register_options(cls, register):
        super().register_options(register)
        register(
            "--resolves",
            type=dict,
            # TODO: Default this to something like {'jvm-default': '3rdparty/jvm/default.lockfile'}.
            # TODO: expand help message
            help="A dictionary mapping resolve names to the path of their lockfile.",
        )
        register(
            "--default-resolve",
            type=str,
            # TODO: Default this to something like `jvm-default`.
            default=None,
            help=(
                "The default value for the `resolve` field used by targets like `junit_test` and "
                "`deploy_jar`.\n\n"
                "The name must be defined as a resolve in `[jvm].resolves`.",
            ),
        )
        register(
            "--default-compatible-resolves",
            type=list,
            member_type=str,
            # TODO: Default this to something like `['jvm-default']`.
            default=[],
            help=(
                "The default value for the `compatible_resolves` field used by targets like "
                "`jvm_artifact` and `java_source`/`scala_source`.\n\n"
                "Each name must be defined as a resolve in `[jvm].resolves`."
            ),
        )

    @property
    def resolves(self) -> dict[str, str]:
        return cast("dict[str, str]", self.options.resolves)

    @property
    def default_resolve(self) -> str | None:
        return cast(str, self.options.default_resolve)

    @property
    def default_compatible_resolves(self) -> tuple[str, ...]:
        return tuple(self.options.default_compatible_resolves)
