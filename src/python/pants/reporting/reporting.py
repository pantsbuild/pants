# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.option.subsystem import Subsystem


class Reporting(Subsystem):
    """V1 reporting config."""

    options_scope = "reporting"

    @classmethod
    def register_options(cls, register):
        super().register_options(register)

        def register_deprecated(*args, **kwargs):
            register(
                *args,
                **kwargs,
                advanced=True,
                help="DEPRECATED: This option is no longer applicable.",
                removal_version="2.1.0.dev0",
                removal_hint=(
                    "This option is no longer applicable. The `[reporting]` subsystem will be "
                    "removed."
                ),
            )

        register_deprecated("--reports-dir")
        register_deprecated("--template-dir")
        register_deprecated("--console-label-format", type=dict)
        register_deprecated("--console-tool-output-format", type=dict)
