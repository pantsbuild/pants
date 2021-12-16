# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from typing import cast

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
                "The default value used for the `resolve` and `compatible_resolves` fields.\n\n"
                "The name must be defined as a resolve in `[jvm].resolves`.",
            ),
        )

    @property
    def resolves(self) -> dict[str, str]:
        return cast("dict[str, str]", self.options.resolves)

    @property
    def default_resolve(self) -> str | None:
        return cast(str, self.options.default_resolve)

    def resolves_for_target(self, target: Target) -> tuple[str, ...]:
        if target.has_field(JvmResolveField):
            val = target[JvmResolveField].value or self.default_resolve
            # TODO: remove once we always have a default resolve.
            if val is None:
                return ()
            if val not in self.resolves:
                raise InvalidFieldException(
                    f"Unrecognized resolve in the {target[JvmResolveField].alias} field for "
                    f"{target.address}: {val}.\n\n"
                    "All valid resolve names (from `[jvm.resolves]`): "
                    f"{sorted(self.resolves.keys())}"
                )
            return (val,)
        if target.has_field(JvmCompatibleResolvesField):
            vals = target[JvmCompatibleResolvesField].value or (
                (self.default_resolve,) if self.default_resolve is not None else ()
            )
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
