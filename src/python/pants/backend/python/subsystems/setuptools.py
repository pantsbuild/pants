# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from typing import Tuple

from pants.backend.python.subsystems.python_tool_base import PythonToolRequirementsBase


class Setuptools(PythonToolRequirementsBase):
    options_scope = "setuptools"
    help = "The Python setuptools library (https://github.com/pypa/setuptools)."

    default_version = "setuptools>=50.3.0,<54.0"
    default_extra_requirements = ["wheel>=0.35.1,<0.37"]

    @classmethod
    def register_options(cls, register):
        super().register_options(register)
        register(
            "--entry-point",
            type=str,
            advanced=True,
            help="DEPRECATED: Unused.",
            removal_version="2.5.0.dev0",
            removal_hint="This option was never used.",
        )

        register(
            "--interpreter-constraints",
            type=list,
            advanced=True,
            help=(
                "DEPRECATED: Python interpreter constraints to use when selecting an interpreter "
                "to package `python_distribution` targets using setup.py."
            ),
            removal_version="2.5.0.dev0",
            removal_hint=(
                "Interpreter constraints for setup.py execution are now derived from the "
                "`python_distribution` being packaged so this option is not needed."
            ),
        )

    @property
    def interpreter_constraints(self) -> Tuple[str, ...]:
        return tuple(self.options.interpreter_constraints)
