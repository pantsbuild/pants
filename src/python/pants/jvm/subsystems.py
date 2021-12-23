# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from typing import cast

from pants.backend.java.subsystems.javac import JavacSubsystem
from pants.base.deprecated import resolve_conflicting_options
from pants.engine.target import InvalidFieldException, Target
from pants.jvm.target_types import JvmCompatibleResolvesField, JvmResolveField
from pants.option.subsystem import Subsystem


class JvmSubsystem(Subsystem):
    options_scope = "jvm"
    help = "Options for general JVM functionality."

    @classmethod
    def register_options(cls, register):
        super().register_options(register)
        register(
            "--jdk",
            default="adopt:1.11",
            advanced=True,
            help=(
                "The JDK to use.\n\n"
                " This string will be passed directly to Coursier's `--jvm` parameter."
                " Run `cs java --available` to see a list of available JVM versions on your platform.\n\n"
                " If the string 'system' is passed, Coursier's `--system-jvm` option will be used"
                " instead, but note that this can lead to inconsistent behavior since the JVM version"
                " will be whatever happens to be found first on the system's PATH."
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
                "The default value used for the `resolve` and `compatible_resolves` fields.\n\n"
                "The name must be defined as a resolve in `[jvm].resolves`.",
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
                "['-agentlib:jdwp=transport=dt_socket,server=y,suspend=y,address=5005']",
            ),
        )

    def jdk(self, javac_subsystem: JavacSubsystem) -> str:
        jdk = resolve_conflicting_options(
            old_option="jdk",
            new_option="jdk",
            old_scope=javac_subsystem.options_scope,
            new_scope=self.options_scope,
            old_container=javac_subsystem.options,
            new_container=self.options,
        )
        return cast(str, jdk)

    @property
    def resolves(self) -> dict[str, str]:
        return cast("dict[str, str]", dict(self.options.resolves))

    @property
    def default_resolve(self) -> str:
        return cast(str, self.options.default_resolve)

    @property
    def debug_args(self) -> tuple[str, ...]:
        return cast("tuple[str, ...]", tuple(self.options.debug_args))

    def resolves_for_target(self, target: Target) -> tuple[str, ...]:
        if target.has_field(JvmResolveField):
            val = target[JvmResolveField].value or self.default_resolve
            if val not in self.resolves:
                raise InvalidFieldException(
                    f"Unrecognized resolve in the {target[JvmResolveField].alias} field for "
                    f"{target.address}: {val}.\n\n"
                    "All valid resolve names (from `[jvm.resolves]`): "
                    f"{sorted(self.resolves.keys())}"
                )
            return (val,)
        if target.has_field(JvmCompatibleResolvesField):
            vals = target[JvmCompatibleResolvesField].value or (self.default_resolve,)
            invalid_resolves = set(vals) - set(self.resolves.keys())
            if invalid_resolves:
                raise InvalidFieldException(
                    f"Unrecognized resolves in the {target[JvmCompatibleResolvesField].alias} "
                    f"field for {target.address}: {sorted(vals)}.\n\n"
                    "All valid resolve names (from `[jvm.resolves]`): "
                    f"{sorted(self.resolves.keys())}"
                )
            return vals
        raise AssertionError(
            f"Invalid target type {target.alias} for {target.address}. Needs to have `resolve` or "
            "`compatible_resolves` field registered."
        )
