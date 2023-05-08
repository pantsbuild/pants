# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from enum import Enum

from pants.option.option_types import BoolOption
from pants.util.docutil import bin_name
from pants.util.strutil import softwrap


class ExportToolOption(BoolOption):
    """An `--export` option to toggle whether the `export` goal should include the tool."""

    def __new__(cls):
        return super().__new__(
            cls,
            default=True,
            removal_version="2.23.0.dev0",
            removal_hint="Use the export goal's --resolve option to select tools to export, instead "
            "of using this option to exempt a tool from export-by-default.",
            help=(
                lambda subsystem_cls: softwrap(
                    f"""
                    If true, export a virtual environment with {subsystem_cls.name} when running
                    `{bin_name()} export`.

                    This can be useful, for example, with IDE integrations to point your editor to
                    the tool's binary.
                    """
                )
            ),
        )


class ExportRules(Enum):
    """The type of lockfile generation strategy to use for a tool.

    - CUSTOM: The subsystem implementer is responsible for the export rules.
    - NO_ICS: The python tool can be exported without worrying about interpreter constraints.
    - WITH_ICS: The python tool must be exported using a FieldSet's interpreter constraints.
        The subsystem must define the `field_set_type` `ClassVar`.
    - WITH_FIRSTPARTY_PLUGINS: The tool not only uses interpreter constraints, but also supports
        first party plugins. The subsystem must define the `firstparty_plugins_type` `ClassVar`.
    """

    CUSTOM = object()
    NO_ICS = object()
    WITH_ICS = object()
    WITH_FIRSTPARTY_PLUGINS = object()
