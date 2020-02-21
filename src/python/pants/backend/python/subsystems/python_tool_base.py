# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from typing import Optional, Sequence, Tuple

from pants.subsystem.subsystem import Subsystem


class PythonToolBase(Subsystem):
    """Base class for subsystems that configure a python tool to be invoked out-of-process."""

    # Subclasses must set.
    default_version: Optional[str] = None
    default_entry_point: Optional[str] = None
    # Subclasses do not need to override.
    default_extra_requirements: Sequence[str] = []
    default_interpreter_constraints: Sequence[str] = []

    @classmethod
    def register_options(cls, register):
        super().register_options(register)
        register(
            "--version",
            type=str,
            advanced=True,
            fingerprint=True,
            default=cls.default_version,
            help="Requirement string for the tool.",
        )
        register(
            "--extra-requirements",
            type=list,
            member_type=str,
            advanced=True,
            fingerprint=True,
            default=cls.default_extra_requirements,
            help="Any additional requirement strings to use with the tool. This is useful if the "
            "tool allows you to install plugins or if you need to constrain a dependency to "
            "a certain version.",
        )
        register(
            "--interpreter-constraints",
            type=list,
            advanced=True,
            fingerprint=True,
            default=cls.default_interpreter_constraints,
            help="Python interpreter constraints for this tool. An empty list uses the default "
            "interpreter constraints for the repo.",
        )
        register(
            "--entry-point",
            type=str,
            advanced=True,
            fingerprint=True,
            default=cls.default_entry_point,
            help="The main module for the tool. If unspecified, the code using this tool "
            "must provide it explicitly on invocation, or it can use the tool as a "
            "library, invoked by a wrapper script.",
        )

    def get_interpreter_constraints(self):
        return self.get_options().interpreter_constraints

    def get_requirement_specs(self) -> Tuple[str, ...]:
        return (self.options.version, *self.options.extra_requirements)

    def get_entry_point(self):
        return self.get_options().entry_point
