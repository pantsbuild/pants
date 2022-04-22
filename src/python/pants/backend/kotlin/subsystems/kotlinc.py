# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from pants.option.option_types import ArgsListOption
from pants.option.subsystem import Subsystem


class KotlincSubsystem(Subsystem):
    options_scope = "kotlinc"
    name = "kotlinc"
    help = "The Kotlin programming language (https://kotlinlang.org/)."

    args = ArgsListOption(
        example="-Werror",
        extra_help="See https://kotlinlang.org/docs/compiler-reference.html for supported arguments.",
    )
