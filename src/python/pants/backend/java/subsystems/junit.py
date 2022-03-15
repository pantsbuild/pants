# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.jvm.resolve.jvm_tool import JvmToolBase
from pants.option.option_types import ArgsListOption
from pants.util.docutil import git_url


class JUnit(JvmToolBase):
    options_scope = "junit"
    name = "JUnit"
    help = "The JUnit test framework (https://junit.org)"

    default_version = "5.7.2"
    default_artifacts = (
        "org.junit.platform:junit-platform-console:1.7.2",
        "org.junit.jupiter:junit-jupiter-engine:{version}",
        "org.junit.vintage:junit-vintage-engine:{version}",
    )
    default_lockfile_resource = ("pants.jvm.test", "junit.default.lockfile.txt")
    default_lockfile_path = "src/python/pants/jvm/test/junit.default.lockfile.txt"
    default_lockfile_url = git_url(default_lockfile_path)

    args = ArgsListOption(example="--disable-ansi-colors", passthrough=True)
