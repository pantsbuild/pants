# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from typing import ClassVar, Sequence, Tuple, cast

from pants.backend.python.target_types import ConsoleScript, EntryPoint, MainSpecification
from pants.option.errors import OptionsError
from pants.option.subsystem import Subsystem


class PythonToolRequirementsBase(Subsystem):
    """Base class for subsystems that configure a set of requirements for a python tool."""

    # Subclasses must set.
    default_version: ClassVar[str]
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
    def requirement(self) -> str:
        return cast(str, self.options.version)

    @property
    def extra_requirements(self) -> Tuple[str, ...]:
        return tuple(self.options.extra_requirements)

    @property
    def all_requirements(self) -> Tuple[str, ...]:
        return (self.requirement, *self.extra_requirements)

    @property
    def interpreter_constraints(self) -> Tuple[str, ...]:
        return tuple(self.options.interpreter_constraints)


class PythonToolBase(PythonToolRequirementsBase):
    """Base class for subsystems that configure a python tool to be invoked out-of-process."""

    # Subclasses must set.
    default_main: ClassVar[MainSpecification]

    @classmethod
    def register_options(cls, register):
        super().register_options(register)
        register(
            "--console-script",
            type=str,
            advanced=True,
            default=cls.default_main.spec if isinstance(cls.default_main, ConsoleScript) else None,
            help=(
                "The console script for the tool. Using this option is generally preferable to "
                "(and mutually exclusive with) specifying an --entry-point since console script "
                "names have a higher expectation of staying stable across releases of the tool. "
                "Usually, you will not want to change this from the default."
            ),
        )
        register(
            "--entry-point",
            type=str,
            advanced=True,
            default=cls.default_main.spec if isinstance(cls.default_main, EntryPoint) else None,
            help=(
                "The entry point for the tool. Generally you only want to use this option if the "
                "tool does not offer a --console-script (which this option is mutually exclusive "
                "with). Usually, you will not want to change this from the default."
            ),
        )

    @property
    def main(self) -> MainSpecification:
        is_default_console_script = self.options.is_default("console_script")
        is_default_entry_point = self.options.is_default("entry_point")
        if not is_default_console_script and not is_default_entry_point:
            raise OptionsError(
                f"Both [{self.scope}].console-script={self.options.console_script} and "
                f"[{self.scope}].entry-point={self.options.entry_point} are configured but these "
                f"options are mutually exclusive. Please pick one."
            )
        if not is_default_console_script:
            return ConsoleScript(cast(str, self.options.console_script))
        if not is_default_entry_point:
            return EntryPoint.parse(cast(str, self.options.entry_point))
        return self.default_main
