# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from pants.core.goals.generate_lockfiles import DEFAULT_TOOL_LOCKFILE
from pants.option.option_types import ArgsListOption, StrListOption, StrOption
from pants.option.subsystem import Subsystem


class Scalac(Subsystem):
    options_scope = "scalac"
    help = "The Scala compiler."

    default_plugins_lockfile_path = (
        "src/python/pants/backend/scala/subsystems/scalac_plugins.default.lockfile.txt"
    )
    default_plugins_lockfile_resource = (
        "pants.backend.scala.subsystems",
        "scalac_plugins.default.lockfile.txt",
    )

    args = ArgsListOption(
        help=f"Global `scalac` compiler flags, e.g. `--{options_scope}-args='-encoding UTF-8'`."
    )
    plugins_global = StrListOption(
        "--plugins-global",
        help=(
            "A list of addresses of `scalac_plugin` targets which should be used for "
            "compilation of all Scala targets in a build.\n\nIf you set this, you must also "
            "set `[scalac].plugins_global_lockfile`."
        ),
    ).advanced()
    plugins_global_lockfile = StrOption(
        "--plugins-global-lockfile",
        default=DEFAULT_TOOL_LOCKFILE,
        help=(
            "The filename of the lockfile for global plugins. You must set this option to a "
            "file path, e.g. '3rdparty/jvm/global_scalac_plugins.lock', if you set "
            "`[scalac].plugins_global`."
        ),
    ).advanced()
