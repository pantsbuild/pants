# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from pants.option.option_types import DictOption, StrListOption, StrOption
from pants.option.subsystem import Subsystem
from pants.util.strutil import softwrap


class JvmSubsystem(Subsystem):
    options_scope = "jvm"
    help = softwrap(
        """
        Options for general JVM functionality.

        JDK strings will be passed directly to Coursier's `--jvm` parameter.
        Run `cs java --available` to see a list of available JVM versions on your platform.

        If the string 'system' is passed, Coursier's `--system-jvm` option will be used
        instead, but note that this can lead to inconsistent behavior since the JVM version
        will be whatever happens to be found first on the system's PATH.
        """
    )

    tool_jdk = StrOption(
        "--tool-jdk",
        default="adopt:1.11",
        help=softwrap(
            """
            The JDK to use when building and running Pants' internal JVM support code and other
            non-compiler tools. See `jvm` help for supported values.
            """
        ),
        advanced=True,
    )
    jdk = StrOption(
        "--jdk",
        default="adopt:1.11",
        help=softwrap(
            """
            The JDK to use.

            This string will be passed directly to Coursier's `--jvm` parameter.
            Run `cs java --available` to see a list of available JVM versions on your platform.

            If the string 'system' is passed, Coursier's `--system-jvm` option will be used
            instead, but note that this can lead to inconsistent behavior since the JVM version
            will be whatever happens to be found first on the system's PATH.
            """
        ),
        advanced=True,
    )
    resolves = DictOption(
        "--resolves",
        default={"jvm-default": "3rdparty/jvm/default.lock"},
        # TODO: expand help message
        help="A dictionary mapping resolve names to the path of their lockfile.",
    )
    default_resolve = StrOption(
        "--default-resolve",
        default="jvm-default",
        help=softwrap(
            """
            The default value used for the `resolve` and `compatible_resolves` fields.

            The name must be defined as a resolve in `[jvm].resolves`.
            """
        ),
    )
    debug_args = StrListOption(
        "--debug-args",
        help=softwrap(
            """
            Extra JVM arguments to use when running tests in debug mode.

            For example, if you want to attach a remote debugger, use something like
            ['-agentlib:jdwp=transport=dt_socket,server=y,suspend=y,address=5005']
            """
        ),
    )
