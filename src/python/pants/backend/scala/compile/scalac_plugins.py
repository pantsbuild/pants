# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from typing import cast

from pants.jvm.resolve.jvm_tool import JvmToolBase
from pants.util.docutil import git_url


class ScalacPlugins(JvmToolBase):
    options_scope = "scalac-plugins"
    help = (
        "Plugins for `scalac`.\n\n"
        "Each artifact specified in `--artifacts` should be loadable as a `scalac` plugin. "
        "Note that the `--version` flag has no meaning in this case, and needn't be set."
    )

    default_artifacts = ()
    default_lockfile_resource = (
        "pants.backend.scala.compile",
        "scalac_plugins.default.lockfile.txt",
    )
    default_lockfile_url = git_url(
        "src/python/pants/backend/scala/compile/scalac_plugins.default.lockfile.txt"
    )

    @classmethod
    def register_options(cls, register):
        super().register_options(register)
        register(
            "--names",
            type=list,
            member_type=str,
            advanced=True,
            default=[],
            help=("The list of plugin names for the associated `--artifacts`."),
        )

    @property
    def names(self) -> list[str]:
        return cast("list[str]", self.options.names)
