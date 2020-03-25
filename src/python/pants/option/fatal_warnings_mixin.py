# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.util.memo import memoized_property


class FatalWarningsMixin:
    """A mixin for global configuration of jvm fatal warnings."""

    @classmethod
    def register_options(cls, register):
        super().register_options(register)
        register(
            "--fatal-warnings-allowed-warnings",
            advanced=True,
            type=list,
            fingerprint=True,
            default=[],
            help="List of warnings that are allowed to happen in a compilation with fatal_warnings enabled. "
            "Represented as a list of strings (not regexes) that are allowed in the message of the warning "
            "(e.g. 'Unused import')",
        )

    @memoized_property
    def get_allowed_fatal_warnings_patterns(self):
        return self.get_options().fatal_warnings_allowed_warnings
