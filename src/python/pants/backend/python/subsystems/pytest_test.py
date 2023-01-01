# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import pytest

from pants.backend.python.subsystems.pytest import PyTest
from pants.option.ranked_value import Rank, RankedValue
from pants.testutil.option_util import create_subsystem


def test_validate_pytest_cov_included() -> None:
    def validate(extra_requirements: list[str] | None = None) -> None:
        extra_reqs_rv = (
            RankedValue(Rank.CONFIG, extra_requirements)
            if extra_requirements is not None
            else RankedValue(Rank.HARDCODED, PyTest.default_extra_requirements)
        )
        pytest = create_subsystem(PyTest, extra_requirements=extra_reqs_rv)
        pytest.validate_pytest_cov_included()

    # Default should not error.
    validate()
    # Canonicalize project name.
    validate(["PyTeST_cOV"])

    with pytest.raises(ValueError) as exc:
        validate([])
    assert "missing `pytest-cov`" in str(exc.value)

    with pytest.raises(ValueError) as exc:
        validate(["custom-plugin"])
    assert "missing `pytest-cov`" in str(exc.value)
