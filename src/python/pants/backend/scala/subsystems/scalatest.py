# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.jvm.resolve.jvm_tool import JvmToolBase
from pants.option.custom_types import shell_str
from pants.util.docutil import git_url


class Scalatest(JvmToolBase):
    options_scope = "scalatest"
    help = "The Scalatest test framework (https://www.scalatest.org/)"

    default_version = "3.2.10"
    default_artifacts = ("org.scalatest:scalatest_2.13:{version}",)
    default_lockfile_resource = ("pants.backend.scala.subsystems", "scalatest.default.lockfile.txt")
    default_lockfile_url = git_url(
        "src/python/pants/backend/scala/subsystems/scalatest.default.lockfile.txt"
    )

    @classmethod
    def register_options(cls, register):
        super().register_options(register)

        register(
            "--args",
            type=list,
            member_type=shell_str,
            passthrough=True,
            help=(
                "Arguments to pass directly to Scalatest, e.g. `-t $testname`. See "
                "https://www.scalatest.org/user_guide/using_the_runner for supported arguments."
            ),
        )
