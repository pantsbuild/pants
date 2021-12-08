# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from typing import cast

from pants.jvm.resolve.jvm_tool import JvmToolBase
from pants.util.docutil import git_url


class ScalafmtSubsystem(JvmToolBase):
    options_scope = "scalafmt"
    help = "scalafmt (https://scalameta.org/scalafmt/)"

    default_version = "3.2.1"
    default_artifacts = ("org.scalameta:scalafmt-cli_2.13:{version}",)
    default_lockfile_resource = (
        "pants.backend.scala.lint.scalafmt",
        "scalafmt.default.lockfile.txt",
    )
    default_lockfile_path = (
        "src/python/pants/backend/scala/lint/scalafmt/scalafmt.default.lockfile.txt"
    )
    default_lockfile_url = git_url(default_lockfile_path)

    @classmethod
    def register_options(cls, register):
        super().register_options(register)
        register(
            "--skip",
            type=bool,
            default=False,
            help=(
                f"Don't use `scalafmt` when running `{register.bootstrap.pants_bin_name} fmt` and "
                f"`{register.bootstrap.pants_bin_name} lint`"
            ),
        )

    @property
    def skip(self) -> bool:
        return cast(bool, self.options.skip)
