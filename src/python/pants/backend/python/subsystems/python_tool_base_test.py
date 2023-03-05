# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import pytest

from pants.backend.python.subsystems.python_tool_base import PythonToolBase
from pants.backend.python.util_rules.pex_requirements import PexRequirements, Resolve
from pants.testutil.option_util import create_subsystem
from pants.util.ordered_set import FrozenOrderedSet


class _DummyTool(PythonToolBase):
    options_scope = "dummy"
    register_lockfile = True
    default_lockfile_resource = ("dummy", "dummy")
    default_lockfile_url = "dummy"


@pytest.mark.parametrize(
    ("req", "proj_name"),
    (
        ("foo==9.99.999", "foo"),
        ("bar>=33.44.55,!=33.44.66", "bar"),
        ("baz[extra]>=42,<43", "baz"),
    ),
)
def test_project_name_from_requirement(req: str, proj_name: str) -> None:
    assert _DummyTool.project_name_from_requirement(req) == proj_name


def test_install_from_resolve_default() -> None:
    tool = create_subsystem(
        _DummyTool,
        lockfile="dummy.lock",
        install_from_resolve="dummy_resolve",
        requirements=["foo", "bar", "baz"],
        version="",
        extra_requirements=[],
    )
    pex_reqs = tool.pex_requirements()
    assert isinstance(pex_reqs, PexRequirements)
    assert pex_reqs.from_superset == Resolve("dummy_resolve")
    assert pex_reqs.req_strings == FrozenOrderedSet(["bar", "baz", "foo"])
