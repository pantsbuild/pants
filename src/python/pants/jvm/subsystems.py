# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from typing import cast

from pants.engine.target import InvalidFieldException, Target
from pants.jvm.target_types import JvmResolveField
from pants.option.subsystem import Subsystem


class JvmSubsystem(Subsystem):
    options_scope = "jvm"
    help = (
        "Options for general JVM functionality.\n\n"
        " JDK strings will be passed directly to Coursier's `--jvm` parameter."
        " Run `cs java --available` to see a list of available JVM versions on your platform.\n\n"
        " If the string 'system' is passed, Coursier's `--system-jvm` option will be used"
        " instead, but note that this can lead to inconsistent behavior since the JVM version"
        " will be whatever happens to be found first on the system's PATH."
    )

    @classmethod
    def register_options(cls, register):
        super().register_options(register)
        register(
            "--tool-jdk",
            default="adopt:1.11",
            advanced=True,
            help=(
                "The JDK to use when building and running Pants' internal JVM support code and other "
                "non-compiler tools. See `jvm` help for supported values."
            ),
        )
        register(
            "--jdk",
            type=str,
            default="adopt:1.11",
            help=(
                "The default JDK to use when compiling sources or running tests for your code.\n\n"
                "See `jvm` help for supported values."
            ),
        )
        register(
            "--resolves",
            type=dict,
            default={"jvm-default": "3rdparty/jvm/default.lock"},
            # TODO: expand help message
            help="A dictionary mapping resolve names to the path of their lockfile.",
        )
        register(
            "--default-resolve",
            type=str,
            default="jvm-default",
            help=(
                "The default value used for the `resolve` field.\n\n"
                "The name must be defined as a resolve in `[jvm].resolves`."
            ),
        )
        register(
            "--debug-args",
            type=list,
            member_type=str,
            default=[],
            help=(
                "Extra JVM arguments to use when running tests in debug mode.\n\n"
                "For example, if you want to attach a remote debugger, use something like "
                "['-agentlib:jdwp=transport=dt_socket,server=y,suspend=y,address=5005']"
            ),
        )

    @property
    def jdk(self) -> str:
        return cast(str, self.options.jdk)

    @property
    def tool_jdk(self) -> str:
        return cast(str, self.options.tool_jdk)

    @property
    def resolves(self) -> dict[str, str]:
        return cast("dict[str, str]", dict(self.options.resolves))

    @property
    def default_resolve(self) -> str:
        return cast(str, self.options.default_resolve)

    @property
    def debug_args(self) -> tuple[str, ...]:
        return cast("tuple[str, ...]", tuple(self.options.debug_args))

    def resolve_for_target(self, target: Target) -> str | None:
        """Return the `JvmResolveField` value or its default for the given target.

        If a Target does not have the `JvmResolveField` returns None, since we can be assured that
        other codepaths will fail to (e.g.) produce a ClasspathEntry if an unsupported target type
        is provided to the JVM rules.
        """
        if not target.has_field(JvmResolveField):
            return None
        val = target[JvmResolveField].value or self.default_resolve
        if val not in self.resolves:
            raise InvalidFieldException(
                f"Unrecognized resolve in the {target[JvmResolveField].alias} field for "
                f"{target.address}: {val}.\n\n"
                "All valid resolve names (from `[jvm.resolves]`): "
                f"{sorted(self.resolves.keys())}"
            )
        return val
