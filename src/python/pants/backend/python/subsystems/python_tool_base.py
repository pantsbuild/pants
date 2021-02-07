# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from typing import ClassVar, Optional, Sequence, Tuple, cast

from pants.option.subsystem import Subsystem


class PythonToolBase(Subsystem):
    """Base class for subsystems that configure a python tool to be invoked out-of-process."""

    # Subclasses must set.
    default_version: ClassVar[Optional[str]] = None
    default_entry_point: ClassVar[Optional[str]] = None
    # Subclasses do not need to override.
    default_extra_requirements: ClassVar[Sequence[str]] = []
    default_interpreter_constraints: ClassVar[Sequence[str]] = []
    register_interpreter_constraints: ClassVar[bool] = False

    @classmethod
    def register_options(cls, register):
        super().register_options(register)
        register(
            "--version",
            type=str,
            advanced=True,
            default=cls.default_version,
            help="Requirement string for the tool.",
        )
        register(
            "--extra-requirements",
            type=list,
            member_type=str,
            advanced=True,
            default=cls.default_extra_requirements,
            help="Any additional requirement strings to use with the tool. This is useful if the "
            "tool allows you to install plugins or if you need to constrain a dependency to "
            "a certain version.",
        )
        register(
            "--entry-point",
            type=str,
            advanced=True,
            default=cls.default_entry_point,
            help=(
                "The main module for the tool. Usually, you will not want to change this from the "
                "default."
            ),
        )

        if cls.default_interpreter_constraints and not cls.register_interpreter_constraints:
            raise ValueError(
                f"`default_interpreter_constraints` are configured for `{cls.options_scope}`, but "
                "`register_interpreter_constraints` is not set to `True`, so the "
                "`--interpreter-constraints` option will not be registered. Did you mean to set "
                "this?"
            )
        if cls.register_interpreter_constraints:
            register(
                "--interpreter-constraints",
                type=list,
                advanced=True,
                default=cls.default_interpreter_constraints,
                help="Python interpreter constraints for this tool.",
            )

    @property
    def version(self) -> Optional[str]:
        return cast(Optional[str], self.options.version)

    @property
    def extra_requirements(self) -> Tuple[str, ...]:
        return tuple(self.options.extra_requirements)

    @property
    def all_requirements(self) -> Tuple[str, ...]:
        return (self.options.version, *self.options.extra_requirements)

    @property
    def interpreter_constraints(self) -> Tuple[str, ...]:
        return tuple(self.options.interpreter_constraints)

    @property
    def entry_point(self) -> Optional[str]:
        return cast(Optional[str], self.options.entry_point)
