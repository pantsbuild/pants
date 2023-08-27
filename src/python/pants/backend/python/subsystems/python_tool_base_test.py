# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from pants.backend.python.subsystems.python_tool_base import PythonToolBase, get_lockfile_metadata
from pants.backend.python.util_rules.interpreter_constraints import InterpreterConstraints
from pants.backend.python.util_rules.lockfile_metadata import PythonLockfileMetadataV3
from pants.backend.python.util_rules.pex_requirements import (
    LoadedLockfile,
    LoadedLockfileRequest,
    Lockfile,
    PexRequirements,
    Resolve,
)
from pants.engine.internals.native_engine import EMPTY_DIGEST
from pants.testutil.option_util import create_subsystem
from pants.testutil.rule_runner import MockGet, run_rule_with_mocks
from pants.util.ordered_set import FrozenOrderedSet


class _DummyTool(PythonToolBase):
    options_scope = "dummy"
    default_lockfile_resource = ("dummy", "dummy")


def test_install_from_resolve_default() -> None:
    tool = create_subsystem(
        _DummyTool,
        lockfile="dummy.lock",
        install_from_resolve="dummy_resolve",
        requirements=["foo", "bar", "baz"],
    )
    pex_reqs = tool.pex_requirements()
    assert isinstance(pex_reqs, PexRequirements)
    assert pex_reqs.from_superset == Resolve("dummy_resolve", False)
    assert pex_reqs.req_strings_or_addrs == FrozenOrderedSet(["bar", "baz", "foo"])


def test_get_lockfile_metadata() -> None:
    tool = create_subsystem(
        _DummyTool,
        lockfile="dummy.lock",
        install_from_resolve="dummy_resolve",
        requirements=["foo", "bar", "baz"],
    )
    metadata = PythonLockfileMetadataV3(
        valid_for_interpreter_constraints=InterpreterConstraints(),
        requirements=set(),
        manylinux=None,
        requirement_constraints=set(),
        only_binary=set(),
        no_binary=set(),
    )
    lockfile = Lockfile("dummy_url", "dummy_description_of_origin", "dummy_resolve")
    loaded_lockfile = LoadedLockfile(EMPTY_DIGEST, "", metadata, 0, True, None, lockfile)
    assert (
        run_rule_with_mocks(
            get_lockfile_metadata,
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
        == metadata
    )
