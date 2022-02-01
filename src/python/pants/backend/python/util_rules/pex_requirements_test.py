# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from pants.backend.python.pip_requirement import PipRequirement
from pants.backend.python.subsystems.setup import InvalidLockfileBehavior
from pants.backend.python.util_rules.interpreter_constraints import InterpreterConstraints
from pants.backend.python.util_rules.lockfile_metadata import (
    PythonLockfileMetadata,
    PythonLockfileMetadataV1,
    PythonLockfileMetadataV2,
)
from pants.backend.python.util_rules.pex_requirements import (
    Lockfile,
    LockfileContent,
    ToolCustomLockfile,
    ToolDefaultLockfile,
    validate_metadata,
)
from pants.engine.fs import FileContent
from pants.testutil.rule_runner import RuleRunner
from pants.util.ordered_set import FrozenOrderedSet


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner()


DEFAULT = "DEFAULT"
FILE = "FILE"

LOCKFILE_TYPES = (DEFAULT, FILE)
BOOLEANS = (True, False)
VERSIONS = (1, 2)


@pytest.mark.parametrize(
    "lockfile_type,invalid_reqs,invalid_constraints,uses_source_plugins,uses_project_ic,version",
    [
        (lft, ir, ic, usp, upi, v)
        for lft in LOCKFILE_TYPES
        for ir in BOOLEANS
        for ic in BOOLEANS
        for usp in BOOLEANS
        for upi in BOOLEANS
        for v in VERSIONS
        if (ir or ic)
    ],
)
def test_validate_metadata(
    rule_runner,
    lockfile_type: str,
    invalid_reqs,
    invalid_constraints,
    uses_source_plugins,
    uses_project_ic,
    version,
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
        actual_digest,
        expected_digest,
        actual_constraints,
        expected_constraints,
        actual_requirements,
        expected_requirements_,
        options_scope_name,
    ) = _metadata_validation_values(
        invalid_reqs, invalid_constraints, uses_source_plugins, uses_project_ic
    )

    metadata: PythonLockfileMetadata
    if version == 1:
        metadata = PythonLockfileMetadataV1(
            InterpreterConstraints([expected_constraints]), expected_digest
        )
    elif version == 2:
        expected_requirements = {PipRequirement.parse(i) for i in expected_requirements_}
        metadata = PythonLockfileMetadataV2(
            InterpreterConstraints([expected_constraints]), expected_requirements
        )
    requirements = _prepare_pex_requirements(
        rule_runner,
        lockfile_type,
        "lockfile_data_goes_here",
        actual_digest,
        actual_requirements,
        options_scope_name,
        uses_source_plugins,
        uses_project_ic,
    )

    python_setup = MagicMock(
        invalid_lockfile_behavior=InvalidLockfileBehavior.warn,
        interpreter_universe=["3.4", "3.5", "3.6", "3.7", "3.8", "3.9", "3.10"],
    )

    validate_metadata(
        metadata, InterpreterConstraints([actual_constraints]), requirements, python_setup
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
    invalid_reqs: bool, invalid_constraints: bool, uses_source_plugins: bool, uses_project_ic: bool
) -> tuple[str, str, str, str, set[str], set[str], str]:

    actual_digest = "900d"
    expected_digest = actual_digest
    actual_reqs = {"ansicolors==0.1.0"}
    expected_reqs = actual_reqs
    if invalid_reqs:
        expected_digest = "baad"
        expected_reqs = {"requests==3.0.0"}

    actual_constraints = "CPython>=3.6,<3.10"
    expected_constraints = actual_constraints
    if invalid_constraints:
        expected_constraints = "CPython>=3.9"

    options_scope_name: str
    if uses_source_plugins and uses_project_ic:
        options_scope_name = "pylint"
    elif uses_source_plugins:
        options_scope_name = "mypy"
    elif uses_project_ic:
        options_scope_name = "bandit"
    else:
        options_scope_name = "kevin"

    return (
        actual_digest,
        expected_digest,
        actual_constraints,
        expected_constraints,
        actual_reqs,
        expected_reqs,
        options_scope_name,
    )


def _prepare_pex_requirements(
    rule_runner: RuleRunner,
    lockfile_type: str,
    lockfile: str,
    expected_digest: str,
    expected_requirements: set[str],
    options_scope_name: str,
    uses_source_plugins: bool,
    uses_project_interpreter_constraints: bool,
) -> Lockfile | LockfileContent:
    if lockfile_type == FILE:
        file_path = "lockfile.txt"
        rule_runner.write_files({file_path: lockfile})
        return ToolCustomLockfile(
            file_path=file_path,
            file_path_description_of_origin="iceland",
            lockfile_hex_digest=expected_digest,
            req_strings=FrozenOrderedSet(expected_requirements),
            options_scope_name=options_scope_name,
            uses_source_plugins=uses_source_plugins,
            uses_project_interpreter_constraints=uses_project_interpreter_constraints,
        )
    elif lockfile_type == DEFAULT:
        content = FileContent("lockfile.txt", lockfile.encode("utf-8"))
        return ToolDefaultLockfile(
            file_content=content,
            lockfile_hex_digest=expected_digest,
            req_strings=FrozenOrderedSet(expected_requirements),
            options_scope_name=options_scope_name,
            uses_source_plugins=uses_source_plugins,
            uses_project_interpreter_constraints=uses_project_interpreter_constraints,
        )
    else:
        raise Exception("incorrect lockfile_type value in test")
