# Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

from packaging.version import Version as V

from pants.backend.python.providers.python_build_standalone.constraints import (
    Constraint,
    ConstraintsList,
)


def test_single_constraints() -> None:
    c_ge = Constraint.parse(">=1.2.3")
    assert c_ge.is_satisified(V("1.2.4"))
    assert c_ge.is_satisified(V("1.2.3"))
    assert not c_ge.is_satisified(V("1.2.2"))

    c_gt = Constraint.parse(">1.2.3")
    assert c_gt.is_satisified(V("1.2.4"))
    assert not c_gt.is_satisified(V("1.2.3"))
    assert not c_gt.is_satisified(V("1.2.2"))

    c_le = Constraint.parse("<=1.2.3")
    assert not c_le.is_satisified(V("1.2.4"))
    assert c_le.is_satisified(V("1.2.3"))
    assert c_le.is_satisified(V("1.2.2"))

    c_lt = Constraint.parse("<1.2.3")
    assert not c_lt.is_satisified(V("1.2.4"))
    assert not c_lt.is_satisified(V("1.2.3"))
    assert c_lt.is_satisified(V("1.2.2"))

    c_eq = Constraint.parse("==1.2.3")
    assert not c_eq.is_satisified(V("1.2.4"))
    assert c_eq.is_satisified(V("1.2.3"))
    assert not c_eq.is_satisified(V("1.2.2"))

    c_ne = Constraint.parse("!=1.2.3")
    assert c_ne.is_satisified(V("1.2.4"))
    assert not c_ne.is_satisified(V("1.2.3"))
    assert c_ne.is_satisified(V("1.2.2"))


def test_constraints_list() -> None:
    cs = ConstraintsList.parse(">=1.2.0,<2")
    assert cs.is_satisified(V("1.2.1"))
    assert cs.is_satisified(V("1.3.0"))
    assert not cs.is_satisified(V("0.9.1"))
    assert not cs.is_satisified(V("2.0.0"))
    assert not cs.is_satisified(V("2.1"))
