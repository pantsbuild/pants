# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.option.custom_types import file_option
from pants.subsystem.subsystem import Subsystem
from pants.util.memo import memoized_property


class LifecycleStubs(Subsystem):
    """A subsystem used to configure workflows for lifecycle tests (Pants stopping and starting)."""

    options_scope = "lifecycle-stubs"

    @classmethod
    def register_options(cls, register):
        super().register_options(register)
        register(
            "--new-interactive-stream-output-file",
            type=file_option,
            default=None,
            help="Redirect interactive output into a separate file.",
        )

    @memoized_property
    def new_interactive_stream_output_file(self):
        return self.get_options().new_interactive_stream_output_file
