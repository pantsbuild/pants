# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from enum import Enum

from pants.jvm.resolve.jvm_tool import JvmToolBase
from pants.option.option_types import ArgsListOption, BoolOption, EnumOption, SkipOption


class GeneratorType(Enum):
    REFLECTION = "reflection"
    ASM = "asm"


class VerbosityMode(Enum):
    SILENT = "silent"
    NORMAL = "normal"
    EXTRA = "extra"


class ResultFormat(Enum):
    TEXT = "text"
    CSV = "csv"
    SCSV = "scsv"
    JSON = "json"
    LATEX = "latex"


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
    verbosity = EnumOption(default=VerbosityMode.NORMAL, help="Level of verbosity.")
    result_format = EnumOption(default=ResultFormat.CSV, help="File format of the results report.")
    fail_on_error = BoolOption(
        default=None,
        help="Whether should JMH fail in case any benchmark suffers from an unrecoverable error.",
    )
    args = ArgsListOption(example="--disable-ansi-colors", passthrough=True)
    skip = SkipOption("bench")
