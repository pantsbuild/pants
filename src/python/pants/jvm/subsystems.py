# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from pants.engine.target import InvalidFieldException, Target
from pants.jvm.target_types import JvmResolveField, JvmResolveField
from pants.option.option_types import DictOption, StrListOption, StrOption
from pants.option.subsystem import Subsystem


class JvmSubsystem(Subsystem):
    options_scope = "jvm"
    help = "Options for general JVM functionality."

    jdk = StrOption(
        "--jdk",
        default="adopt:1.11",
        help=(
            "The JDK to use.\n\n"
            " This string will be passed directly to Coursier's `--jvm` parameter."
            " Run `cs java --available` to see a list of available JVM versions on your platform.\n\n"
            " If the string 'system' is passed, Coursier's `--system-jvm` option will be used"
            " instead, but note that this can lead to inconsistent behavior since the JVM version"
            " will be whatever happens to be found first on the system's PATH."
        ),
    ).advanced()
    resolves = DictOption(
        "--resolves",
        default={"jvm-default": "3rdparty/jvm/default.lock"},
        # TODO: expand help message
        help="A dictionary mapping resolve names to the path of their lockfile.",
    )
    default_resolve = StrOption(
        "--default-resolve",
        default="jvm-default",
        help=(
            "The default value used for the `resolve` and `compatible_resolves` fields.\n\n"
            "The name must be defined as a resolve in `[jvm].resolves`."
        ),
    )
    debug_args = StrListOption(
        "--debug-args",
        help=(
            "Extra JVM arguments to use when running tests in debug mode.\n\n"
            "For example, if you want to attach a remote debugger, use something like "
            "['-agentlib:jdwp=transport=dt_socket,server=y,suspend=y,address=5005']"
        ),
    )

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
