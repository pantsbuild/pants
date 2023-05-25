# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from enum import Enum

from pants.jvm.resolve.jvm_tool import JvmToolBase
from pants.option.option_types import ArgsListOption, EnumOption, SkipOption


class GeneratorType(Enum):
    REFLECTION = "reflection"
    ASM = "asm"


class Jmh(JvmToolBase):
    options_scope = "jmh"
    name = "JMH"
    help = "The Java Microbenchmark Harness (https://github.com/openjdk/jmh)"

    default_version = "1.36"
    default_artifacts = (
        "org.openjdk.jmh:jmh-core:{version}",
        "org.openjdk.jmh:jmh-generator-bytecode:{version}",
        "org.openjdk.jmh:jmh-generator-reflection:{version}",
        "org.openjdk.jmh:jmh-generator-asm:{version}",
    )
    default_lockfile_resource = ("pants.jvm.bench", "jmh.default.lockfile.txt")

    generator_type = EnumOption(
        "--generator_type",
        default=GeneratorType.REFLECTION,
        help="Type of bytecode generation to use.",
    )
    args = ArgsListOption(example="--disable-ansi-colors", passthrough=True)
    skip = SkipOption("bench")
