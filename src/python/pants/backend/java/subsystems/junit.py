# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.jvm.resolve.jvm_tool import JvmToolBase
from pants.option.custom_types import shell_str
from pants.util.docutil import git_url


class JUnit(JvmToolBase):
    options_scope = "junit"
    help = "The JUnit test framework (https://junit.org)"

    default_version = "5.7.2"
    default_artifacts = (
        "org.junit.platform:junit-platform-console:1.7.2",
        "org.junit.jupiter:junit-jupiter-engine:{version}",
        "org.junit.vintage:junit-vintage-engine:{version}",
    )
    default_lockfile_resource = ("pants.jvm.test", "junit.default.lockfile.txt")
    default_lockfile_url = git_url("src/python/pants/jvm/test/junit.default.lockfile.txt")

    @classmethod
    def register_options(cls, register):
        super().register_options(register)

        register(
            "--args",
            type=list,
            member_type=shell_str,
            passthrough=True,
            help="Arguments to pass directly to JUnit, e.g. `--disable-ansi-colors`",
        )
