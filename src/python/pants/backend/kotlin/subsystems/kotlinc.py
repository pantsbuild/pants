# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

from pants.option.option_types import ArgsListOption, DictOption
from pants.option.subsystem import Subsystem
from pants.util.strutil import softwrap


class KotlincSubsystem(Subsystem):
    options_scope = "kotlinc"
    name = "kotlinc"
    help = "The Kotlin programming language (https://kotlinlang.org/)."

    args = ArgsListOption(
        example="-Werror",
        extra_help="See https://kotlinlang.org/docs/compiler-reference.html for supported arguments.",
    )

    # TODO: see if we can use an actual list mechanism? If not, this seems like an OK option
    default_plugins = DictOption[str](
        "--plugins-for-resolve",
        help=softwrap(
            """
            A dictionary, whose keys are the names of each JVM resolve that requires default
            `kotlinc` plugins, and the value is a comma-separated string consisting of kotlinc plugin
            names. Each specified plugin must have a corresponding `kotlinc_plugin` target that specifies
            that name in either its `plugin_name` field or is the same as its target name.
            """
        ),
    )

    def parsed_default_plugins(self) -> dict[str, list[str]]:
        return {
            key: [i.strip() for i in value.split(",")]
            for key, value in self.default_plugins.items()
        }
