# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass

from pants.backend.python.goals.run_helper import _create_python_source_run_request
from pants.backend.python.target_types import PexEntryPointField, PythonSourceField
from pants.backend.python.util_rules.pex_environment import PexEnvironment
from pants.core.goals.run import RunFieldSet, RunRequest
from pants.engine.rules import collect_rules, rule
from pants.engine.unions import UnionRule
from pants.util.logging import LogLevel


@dataclass(frozen=True)
class PythonSourceFieldSet(RunFieldSet):
    required_fields = (PythonSourceField,)

    source: PythonSourceField


@rule(level=LogLevel.DEBUG)
async def create_python_source_run_request(
    field_set: PythonSourceFieldSet, pex_env: PexEnvironment
) -> RunRequest:
    return await _create_python_source_run_request(
        field_set.address,
        entry_point_field=PexEntryPointField(field_set.source.value, field_set.address),
        pex_env=pex_env,
        # @TODO: How should we make this customizable?
        # `False` is backwards-compatible behavior right now
        run_in_sandbox=False,
        # Setting --venv is kosher because the PEX we create is just for the thirdparty deps.
        additional_pex_args=["--venv"],
    )


def rules():
    return [
        *collect_rules(),
        UnionRule(RunFieldSet, PythonSourceFieldSet),
    ]
