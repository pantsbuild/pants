# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import pytest

from pants.backend.python.goals.pytest_runner import validate_pytest_cov_included
from pants.backend.python.pip_requirement import PipRequirement
from pants.backend.python.subsystems.pytest import PyTest
from pants.backend.python.util_rules.interpreter_constraints import InterpreterConstraints
from pants.backend.python.util_rules.lockfile_metadata import PythonLockfileMetadataV3
from pants.backend.python.util_rules.pex_requirements import (
    LoadedLockfile,
    LoadedLockfileRequest,
    Lockfile,
    Resolve,
)
from pants.engine.internals.native_engine import EMPTY_DIGEST
from pants.testutil.option_util import create_subsystem
from pants.testutil.rule_runner import MockGet, run_rule_with_mocks


@pytest.mark.parametrize("entire_lockfile", [False, True])
def test_validate_pytest_cov_included(entire_lockfile: bool) -> None:
    def validate(reqs: list[str]) -> None:
        if entire_lockfile:
            tool = create_subsystem(
                PyTest,
                lockfile="dummy.lock",
                install_from_resolve="dummy_resolve",
                requirements=[],
            )
        else:
            tool = create_subsystem(
                PyTest,
                lockfile="dummy.lock",
                install_from_resolve="dummy_resolve",
                requirements=reqs,
            )
        lockfile = Lockfile("dummy_url", "dummy_description_of_origin", "dummy_resolve")
        metadata = PythonLockfileMetadataV3(
            valid_for_interpreter_constraints=InterpreterConstraints(),
            requirements={PipRequirement.parse(req) for req in reqs},
            manylinux=None,
            requirement_constraints=set(),
            only_binary=set(),
            no_binary=set(),
        )
        loaded_lockfile = LoadedLockfile(EMPTY_DIGEST, "", metadata, 0, True, None, lockfile)
        run_rule_with_mocks(
            validate_pytest_cov_included,
            rule_args=[tool],
            mock_gets=[
                MockGet(Lockfile, (Resolve,), lambda x: lockfile),
                MockGet(
                    LoadedLockfile,
                    (LoadedLockfileRequest,),
                    lambda x: loaded_lockfile if x.lockfile == lockfile else None,
                ),
            ],
        )

    # Canonicalize project name.
    validate(["PyTeST_cOV"])

    with pytest.raises(ValueError) as exc:
        validate([])
    assert "missing `pytest-cov`" in str(exc.value)

    with pytest.raises(ValueError) as exc:
        validate(["custom-plugin"])
    assert "missing `pytest-cov`" in str(exc.value)
