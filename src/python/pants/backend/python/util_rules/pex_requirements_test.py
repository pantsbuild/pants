# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from pants.backend.python.pip_requirement import PipRequirement
from pants.backend.python.subsystems.setup import InvalidLockfileBehavior
from pants.backend.python.util_rules.interpreter_constraints import InterpreterConstraints
from pants.backend.python.util_rules.lockfile_metadata import PythonLockfileMetadataV2
from pants.backend.python.util_rules.pex_requirements import (
    Lockfile,
    LockfileContent,
    ToolCustomLockfile,
    ToolDefaultLockfile,
    maybe_validate_metadata,
)
from pants.engine.fs import FileContent
from pants.util.ordered_set import FrozenOrderedSet

DEFAULT = "DEFAULT"
FILE = "FILE"


@pytest.mark.parametrize(
    "lockfile_type,invalid_reqs,invalid_constraints,uses_source_plugins,uses_project_ic",
    [
        (lockfile_type, invalid_reqs, invalid_constraints, source_plugins, project_ics)
        for lockfile_type in (DEFAULT, FILE)
        for invalid_reqs in (True, False)
        for invalid_constraints in (True, False)
        for source_plugins in (True, False)
        for project_ics in (True, False)
        if (invalid_reqs or invalid_constraints)
    ],
)
def test_validate_metadata(
    lockfile_type: str,
    invalid_reqs,
    invalid_constraints,
    uses_source_plugins,
    uses_project_ic,
    caplog,
) -> None:
    class M:
        opening_default = "You are using the `<default>` lockfile provided by Pants"
        opening_file = "You are using the lockfile at"

        invalid_requirements = (
            "You have set different requirements than those used to generate the lockfile"
        )
        invalid_requirements_source_plugins = ".source_plugins`, and"

        invalid_interpreter_constraints = "You have set interpreter constraints"
        invalid_interpreter_constraints_tool_ics = (
            ".interpreter_constraints`, or by using a new custom lockfile."
        )
        invalid_interpreter_constraints_project_ics = (
            "determines its interpreter constraints based on your code's own constraints."
        )

        closing_lockfile_content = (
            "To generate a custom lockfile based on your current configuration"
        )
        closing_file = "To regenerate your lockfile based on your current configuration"

    (
        actual_constraints,
        expected_constraints,
        actual_requirements,
        expected_requirements,
    ) = _metadata_validation_values(invalid_reqs, invalid_constraints)

    metadata = PythonLockfileMetadataV2(
        InterpreterConstraints([expected_constraints]), expected_requirements
    )
    requirements = _prepare_pex_requirements(
        lockfile_type,
        actual_requirements,
        uses_source_plugins,
        uses_project_ic,
    )

    python_setup = MagicMock(
        invalid_lockfile_behavior=InvalidLockfileBehavior.warn,
        interpreter_universe=["3.4", "3.5", "3.6", "3.7", "3.8", "3.9", "3.10"],
    )

    maybe_validate_metadata(
        lambda: metadata, InterpreterConstraints([actual_constraints]), requirements, python_setup
    )

    txt = caplog.text.strip()

    expected_opening = {
        DEFAULT: M.opening_default,
        FILE: M.opening_file,
    }[lockfile_type]

    assert expected_opening in txt

    if invalid_reqs:
        assert M.invalid_requirements in txt
        if uses_source_plugins:
            assert M.invalid_requirements_source_plugins in txt
        else:
            assert M.invalid_requirements_source_plugins not in txt
    else:
        assert M.invalid_requirements not in txt

    if invalid_constraints:
        assert M.invalid_interpreter_constraints in txt
        if uses_project_ic:
            assert M.invalid_interpreter_constraints_project_ics in txt
            assert M.invalid_interpreter_constraints_tool_ics not in txt
        else:
            assert M.invalid_interpreter_constraints_project_ics not in txt
            assert M.invalid_interpreter_constraints_tool_ics in txt

    else:
        assert M.invalid_interpreter_constraints not in txt

    if lockfile_type == FILE:
        assert M.closing_lockfile_content not in txt
        assert M.closing_file in txt


def _metadata_validation_values(
    invalid_reqs: bool, invalid_constraints: bool
) -> tuple[str, str, set[str], set[PipRequirement]]:
    actual_reqs = {"ansicolors==0.1.0"}
    expected_reqs = {"requests==3.0.0"} if invalid_reqs else actual_reqs
    actual_constraints = "CPython>=3.6,<3.10"
    expected_constraints = "CPython>=3.9" if invalid_constraints else actual_constraints
    return (
        actual_constraints,
        expected_constraints,
        actual_reqs,
        {PipRequirement.parse(r) for r in expected_reqs},
    )


def _prepare_pex_requirements(
    lockfile_type: str,
    expected_requirements: set[str],
    uses_source_plugins: bool,
    uses_project_interpreter_constraints: bool,
) -> Lockfile | LockfileContent:
    if lockfile_type == FILE:
        return ToolCustomLockfile(
            file_path="lock.txt",
            file_path_description_of_origin="",
            lockfile_hex_digest=None,
            req_strings=FrozenOrderedSet(expected_requirements),
            options_scope_name="my_tool",
            uses_source_plugins=uses_source_plugins,
            uses_project_interpreter_constraints=uses_project_interpreter_constraints,
        )
    elif lockfile_type == DEFAULT:
        return ToolDefaultLockfile(
            file_content=FileContent("", b""),
            lockfile_hex_digest=None,
            req_strings=FrozenOrderedSet(expected_requirements),
            options_scope_name="my_tool",
            uses_source_plugins=uses_source_plugins,
            uses_project_interpreter_constraints=uses_project_interpreter_constraints,
        )
    else:
        raise Exception("incorrect lockfile_type value in test")
