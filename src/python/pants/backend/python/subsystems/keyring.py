# Copyright 2025 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
import dataclasses
from typing import Iterable

from pants.backend.python.subsystems.python_tool_base import PythonToolBase
from pants.backend.python.target_types import ConsoleScript, MainSpecification
from pants.backend.python.util_rules.interpreter_constraints import InterpreterConstraints
from pants.backend.python.util_rules.pex import PexRequest
from pants.engine.fs import Digest
from pants.option.option_types import BoolOption


class KeyringSubsystem(PythonToolBase):
    options_scope = "keyring"
    name = "Keyring"
    help_short = "The keyring utility used to authenticate to private PyPI repositories."

    default_version = "keyring==23.4.1"
    default_main = ConsoleScript("keyring")

    default_requirements = ["keyring"]
    default_interpreter_constraints = ["CPython>=3.6,<4"]
    default_lockfile_resource = ("pants.backend.python.subsystems", "keyring.lock")

    register_interpreter_constraints = True

    enabled = BoolOption(
        help="Enable keyring, which enables authentication to private PyPI repos.", default=False
    )

    def to_pex_request(
        self,
        *,
        interpreter_constraints: InterpreterConstraints | None = None,
        extra_requirements: Iterable[str] = (),
        main: MainSpecification | None = None,
        sources: Digest | None = None,
    ) -> PexRequest:
        return dataclasses.replace(
            super().to_pex_request(
                interpreter_constraints=interpreter_constraints,
                extra_requirements=extra_requirements,
                main=main,
                sources=sources,
            ),
            allow_keyring=False,
        )


def rules():
    return KeyringSubsystem.rules()
