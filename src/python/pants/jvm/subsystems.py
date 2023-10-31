# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from pants.option.option_types import BoolOption, DictOption, IntOption, StrListOption, StrOption
from pants.option.subsystem import Subsystem
from pants.util.strutil import help_text, softwrap


class JvmSubsystem(Subsystem):
    options_scope = "jvm"
    help = help_text(
        """
        Options for general JVM functionality.

        JDK strings will be passed directly to Coursier's `--jvm` parameter.
        Run `cs java --available` to see a list of available JVM versions on your platform.

        If the string `'system'` is passed, Coursier's `--system-jvm` option will be used
        instead, but note that this can lead to inconsistent behavior since the JVM version
        will be whatever happens to be found first on the system's PATH.
        """
    )

    class EnvironmentAware:
        global_options = StrListOption(
            help=softwrap(
                """
                List of JVM options to pass to all JVM processes.

                Options set here will be used by any JVM processes required by Pants, with
                the exception of heap memory settings like `-Xmx`, which need to be set
                using `[GLOBAL].process_total_child_memory_usage` and `[GLOBAL].process_per_child_memory_usage`.
                """
            ),
            advanced=True,
        )

    tool_jdk = StrOption(
        default="temurin:1.11",
        help=softwrap(
            """
            The JDK to use when building and running Pants' internal JVM support code and other
            non-compiler tools. See `jvm` help for supported values.
            """
        ),
        advanced=True,
    )
    jdk = StrOption(
        default="temurin:1.11",
        help=softwrap(
            """
            The JDK to use.

            This string will be passed directly to Coursier's `--jvm` parameter.
            Run `cs java --available` to see a list of available JVM versions on your platform.

            If the string `'system'` is passed, Coursier's `--system-jvm` option will be used
            instead, but note that this can lead to inconsistent behavior since the JVM version
            will be whatever happens to be found first on the system's PATH.
            """
        ),
        advanced=True,
    )
    resolves = DictOption(
        default={"jvm-default": "3rdparty/jvm/default.lock"},
        # TODO: expand help message
        help="A dictionary mapping resolve names to the path of their lockfile.",
    )
    default_resolve = StrOption(
        default="jvm-default",
        help=softwrap(
            """
            The default value used for the `resolve` and `compatible_resolves` fields.

            The name must be defined as a resolve in `[jvm].resolves`.
            """
        ),
    )
    debug_args = StrListOption(
        help=softwrap(
            """
            Extra JVM arguments to use when running tests in debug mode.

            For example, if you want to attach a remote debugger, use something like
            `['-agentlib:jdwp=transport=dt_socket,server=y,suspend=y,address=5005']`.
            """
        ),
    )
    reproducible_jars = BoolOption(
        default=False,
        help=softwrap(
            """
            When enabled, JAR files produced by JVM tools will have timestamps stripped.

            Because some compilers do not support this step as a native operation, it can have a
            performance cost, and is not enabled by default.
            """
        ),
        advanced=True,
    )
    # See https://github.com/pantsbuild/pants/issues/14937 for discussion of one way to improve
    # our behavior around cancellation with nailgun.
    nailgun_remote_cache_speculation_delay = IntOption(
        default=1000,
        help=softwrap(
            """
            The time in milliseconds to delay speculation of nailgun processes while reading
            from the remote cache.

            When speculating, a remote cache hit will cancel the local copy of a process. But
            because nailgun does not natively support cancellation, that requires killing a
            nailgun server, which will mean that future processes take longer to warm up.

            This setting allows for trading off waiting for potentially slow cache entries
            against potentially having to warm up a new nailgun server.
            """
        ),
        advanced=True,
    )
