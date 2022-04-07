# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from pants.core.goals.generate_lockfiles import DEFAULT_TOOL_LOCKFILE
from pants.option.option_types import ArgsListOption, DictOption, StrListOption, StrOption
from pants.option.subsystem import Subsystem


class Scalac(Subsystem):
    options_scope = "scalac"
    name = "scalac"
    help = "The Scala compiler."

    default_plugins_lockfile_path = (
        "src/python/pants/backend/scala/subsystems/scalac_plugins.default.lockfile.txt"
    )
    default_plugins_lockfile_resource = (
        "pants.backend.scala.subsystems",
        "scalac_plugins.default.lockfile.txt",
    )

    args = ArgsListOption(example="-encoding UTF-8")
    plugins_global = StrListOption(
        "--plugins-global",
        help=(
            "A list of addresses of `scalac_plugin` targets which should be used for "
            "compilation of all Scala targets in a build.\n\nIf you set this, you must also "
            "set `[scalac].plugins_global_lockfile`."
        ),
        advanced=True,
        removal_version="2.12.0.dev2",
        removal_hint="Use `--scalac-plugins-for-resolve` instead to use user resolves",
    )

    # TODO: see if we can use an actual list mechanism? If not, this seems like an OK option
    default_plugins = DictOption[str](
        "--plugins-for-resolve",
        help=(
            "A dictionary, whose keys are the names of each JVM resolve that requires default "
            "`scalac` plugins, and the value is a comma-separated string consisting of scalac plugin "
            "names. Each specified plugin must have a corresponding `scalac_plugin` target that specifies "
            "that name in either its `plugin_name` field or is the same as its target name."
        ),
    )

    plugins_global_lockfile = StrOption(
        "--plugins-global-lockfile",
        default=DEFAULT_TOOL_LOCKFILE,
        help=(
            "The filename of the lockfile for global plugins. You must set this option to a "
            "file path, e.g. '3rdparty/jvm/global_scalac_plugins.lock', if you set "
            "`[scalac].plugins_global`."
        ),
        advanced=True,
        removal_version="2.12.0.dev2",
        removal_hint="Use `--scalac-plugins-for-resolve` instead, which will add plugin dependencies to JVM user resolves.",
    )

    def parsed_default_plugins(self) -> dict[str, list[str]]:
        return {
            key: [i.strip() for i in value.split(",")]
            for key, value in self.default_plugins.items()
        }
