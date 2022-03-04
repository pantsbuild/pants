# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.jvm.resolve.jvm_tool import JvmToolBase
from pants.option.option_types import ArgsListOption
from pants.util.docutil import git_url


class Scalatest(JvmToolBase):
    options_scope = "scalatest"
    name = "Scalatest"
    help = "The Scalatest test framework (https://www.scalatest.org/)"

    default_version = "3.2.10"
    default_artifacts = ("org.scalatest:scalatest_2.13:{version}",)
    default_lockfile_resource = ("pants.backend.scala.subsystems", "scalatest.default.lockfile.txt")
    default_lockfile_path = (
        "src/python/pants/backend/scala/subsystems/scalatest.default.lockfile.txt"
    )
    default_lockfile_url = git_url(default_lockfile_path)

    args = ArgsListOption(
        example="-t $testname",
        passthrough=True,
        extra_help="See https://www.scalatest.org/user_guide/using_the_runner for supported arguments.",
    )
