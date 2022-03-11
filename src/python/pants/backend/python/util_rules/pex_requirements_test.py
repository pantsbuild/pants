# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import pytest

from pants.backend.python.pip_requirement import PipRequirement
from pants.backend.python.subsystems.setup import InvalidLockfileBehavior, PythonSetup
from pants.backend.python.util_rules.interpreter_constraints import InterpreterConstraints
from pants.backend.python.util_rules.lockfile_metadata import PythonLockfileMetadataV2
from pants.backend.python.util_rules.pex_requirements import (
    Lockfile,
    ToolCustomLockfile,
    ToolDefaultLockfile,
    maybe_validate_metadata,
)
from pants.core.util_rules.lockfile_metadata import InvalidLockfileError
from pants.engine.fs import FileContent
from pants.testutil.option_util import create_subsystem
from pants.util.ordered_set import FrozenOrderedSet

METADATA = PythonLockfileMetadataV2(
    InterpreterConstraints(["==3.8.*"]),
    {PipRequirement.parse("ansicolors"), PipRequirement.parse("requests")},
)


def create_tool_lock(
    req_strings: list[str],
    *,
    default_lock: bool = False,
    uses_source_plugins: bool = False,
    uses_project_interpreter_constraints: bool = False,
) -> ToolDefaultLockfile | ToolCustomLockfile:
    common_kwargs = dict(
        req_strings=FrozenOrderedSet(req_strings),
        resolve_name="my_tool",
        uses_source_plugins=uses_source_plugins,
        uses_project_interpreter_constraints=uses_project_interpreter_constraints,
    )
    return (
        ToolDefaultLockfile(file_content=FileContent("", b""), **common_kwargs)  # type: ignore[arg-type]
        if default_lock
        else ToolCustomLockfile(
            file_path="lock.txt", file_path_description_of_origin="", **common_kwargs  # type: ignore[arg-type]
        )
    )


def create_python_setup(
    behavior: InvalidLockfileBehavior, *, enable_resolves: bool = True
) -> PythonSetup:
    return create_subsystem(
        PythonSetup,
        invalid_lockfile_behavior=behavior,
        resolves_generate_lockfiles=enable_resolves,
        interpreter_versions_universe=PythonSetup.default_interpreter_universe,
    )


def test_invalid_lockfile_behavior_option(caplog) -> None:
    """Test that you can toggle between warnings, errors, and ignoring."""

    def validate(behavior: InvalidLockfileBehavior) -> None:
        maybe_validate_metadata(
            lambda: METADATA,
            METADATA.valid_for_interpreter_constraints,
            create_tool_lock(["bad-req"]),
            create_python_setup(behavior),
        )

    caplog.clear()
    validate(InvalidLockfileBehavior.ignore)
    assert not caplog.records

    validate(InvalidLockfileBehavior.warn)
    assert caplog.records
    assert "./pants generate-lockfiles" in caplog.text
    caplog.clear()

    with pytest.raises(InvalidLockfileError, match="./pants generate-lockfiles"):
        validate(InvalidLockfileBehavior.error)


@pytest.mark.parametrize(
    "is_default_lock,invalid_reqs,invalid_constraints,uses_source_plugins,uses_project_ic",
    [
        (is_default_lock, invalid_reqs, invalid_constraints, source_plugins, project_ics)
        for is_default_lock in (True, False)
        for invalid_reqs in (True, False)
        for invalid_constraints in (True, False)
        for source_plugins in (True, False)
        for project_ics in (True, False)
        if (invalid_reqs or invalid_constraints)
    ],
)
def test_validate_tool_lockfiles(
    is_default_lock: bool,
    invalid_reqs: bool,
    invalid_constraints: bool,
    uses_source_plugins: bool,
    uses_project_ic: bool,
    caplog,
) -> None:
    runtime_interpreter_constraints = (
        InterpreterConstraints(["==2.7.*"])
        if invalid_constraints
        else METADATA.valid_for_interpreter_constraints
    )
    requirements = create_tool_lock(
        ["bad-req"] if invalid_reqs else [str(r) for r in METADATA.requirements],
        default_lock=is_default_lock,
        uses_source_plugins=uses_source_plugins,
        uses_project_interpreter_constraints=uses_project_ic,
    )
    maybe_validate_metadata(
        lambda: METADATA,
        runtime_interpreter_constraints,
        requirements,
        create_python_setup(InvalidLockfileBehavior.warn),
    )

    def contains(msg: str, if_: bool) -> None:
        assert (msg in caplog.text) is if_

    contains("You are using the `<default>` lockfile provided by Pants", if_=is_default_lock)
    contains("You are using the lockfile at lock.txt", if_=not is_default_lock)

    contains("You have set different requirements", if_=invalid_reqs)
    contains("In the input requirements, but not in the lockfile: ['bad-req']", if_=invalid_reqs)
    contains(
        "In the lockfile, but not in the input requirements: ['ansicolors', 'requests']",
        if_=invalid_reqs,
    )
    contains(".source_plugins`, and", if_=invalid_reqs and uses_source_plugins)

    contains("You have set interpreter constraints", if_=invalid_constraints)
    contains(
        "determines its interpreter constraints based on your code's own constraints.",
        if_=invalid_constraints and uses_project_ic,
    )
    contains(
        ".interpreter_constraints`, or by using a new custom lockfile.",
        if_=invalid_constraints and not uses_project_ic,
    )

    contains(
        "To generate a custom lockfile based on your current configuration", if_=is_default_lock
    )
    contains(
        "To regenerate your lockfile based on your current configuration", if_=not is_default_lock
    )


@pytest.mark.parametrize(
    "invalid_reqs,invalid_constraints",
    [
        (invalid_reqs, invalid_constraints)
        for invalid_reqs in (True, False)
        for invalid_constraints in (True, False)
        if (invalid_reqs or invalid_constraints)
    ],
)
def test_validate_user_lockfiles(
    invalid_reqs: bool,
    invalid_constraints: bool,
    caplog,
) -> None:
    runtime_interpreter_constraints = (
        InterpreterConstraints(["==2.7.*"])
        if invalid_constraints
        else METADATA.valid_for_interpreter_constraints
    )
    lockfile = Lockfile(
        file_path="lock.txt",
        file_path_description_of_origin="foo",
        resolve_name="a",
        req_strings=FrozenOrderedSet(
            ["bad-req"] if invalid_reqs else [str(r) for r in METADATA.requirements]
        ),
    )

    # Ignore validation if resolves are manually managed.
    maybe_validate_metadata(
        lambda: METADATA,
        runtime_interpreter_constraints,
        lockfile,
        create_python_setup(InvalidLockfileBehavior.warn, enable_resolves=False),
    )
    assert not caplog.text

    maybe_validate_metadata(
        lambda: METADATA,
        runtime_interpreter_constraints,
        lockfile,
        create_python_setup(InvalidLockfileBehavior.warn),
    )

    def contains(msg: str, if_: bool = True) -> None:
        assert (msg in caplog.text) is if_

    contains("You are using the lockfile at lock.txt to install the resolve `a`")
    contains(
        "The targets use requirements that are not in the lockfile: ['bad-req']", if_=invalid_reqs
    )
    contains("The targets use interpreter constraints", if_=invalid_constraints)
    contains("./pants generate-lockfiles --resolve=a`")
