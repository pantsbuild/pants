# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import asdict
from typing import Any
from unittest.mock import Mock

import pytest

from pants.backend.python.subsystems.setup import PythonSetup
from pants.backend.python.target_types import (
    PythonRequirementsField,
    PythonRequirementTarget,
    PythonResolveField,
    PythonSourceField,
    PythonSourceTarget,
)
from pants.build_graph.address import Address
from pants.core.goals.generate_lockfiles import (
    DEFAULT_TOOL_LOCKFILE,
    AmbiguousResolveNamesError,
    GenerateLockfile,
    GenerateLockfileWithEnvironments,
    KnownUserResolveNames,
    LockfileDiff,
    LockfileDiffPrinter,
    LockfilePackages,
    NoCompatibleResolveException,
    RequestedUserResolveNames,
    UnrecognizedResolveNamesError,
    _preferred_environment,
    determine_resolves_to_generate,
    filter_lockfiles_for_unconfigured_exportable_tools,
)
from pants.core.goals.resolves import ExportableTool
from pants.engine.console import Console
from pants.engine.environment import EnvironmentName
from pants.engine.target import Dependencies, Target
from pants.testutil.option_util import create_subsystem
from pants.util.strutil import softwrap


def test_determine_tool_sentinels_to_generate() -> None:
    class Lang1Requested(RequestedUserResolveNames):
        pass

    class Lang2Requested(RequestedUserResolveNames):
        pass

    lang1_resolves = KnownUserResolveNames(
        ("u1", "u2"), option_name="[lang1].resolves", requested_resolve_names_cls=Lang1Requested
    )
    lang2_resolves = KnownUserResolveNames(
        ("u3",), option_name="[lang2].resolves", requested_resolve_names_cls=Lang2Requested
    )

    def assert_chosen(
        requested: set[str],
        expected_user_resolves: list[RequestedUserResolveNames],
    ) -> None:
        user_resolves = determine_resolves_to_generate([lang1_resolves, lang2_resolves], requested)
        assert user_resolves == expected_user_resolves

    assert_chosen(
        {"u2"},
        expected_user_resolves=[Lang1Requested(["u2"])],
    )

    # If none are specifically requested, return all.
    assert_chosen(
        set(),
        expected_user_resolves=[Lang1Requested(["u1", "u2"]), Lang2Requested(["u3"])],
    )

    with pytest.raises(UnrecognizedResolveNamesError):
        assert_chosen({"fake"}, expected_user_resolves=[])

    # Error if the same resolve name is used for multiple user lockfiles.
    with pytest.raises(AmbiguousResolveNamesError):
        determine_resolves_to_generate(
            [
                KnownUserResolveNames(
                    ("ambiguous",),
                    "[lang1].resolves",
                    requested_resolve_names_cls=Lang1Requested,
                ),
                KnownUserResolveNames(
                    ("ambiguous",),
                    "[lang2].resolves",
                    requested_resolve_names_cls=Lang1Requested,
                ),
            ],
            set(),
        )


def test_no_compatible_resolve_error() -> None:
    python_setup = create_subsystem(PythonSetup, resolves={"a": "", "b": ""}, enable_resolves=True)
    t1 = PythonRequirementTarget(
        {
            PythonRequirementsField.alias: [],
            PythonResolveField.alias: "a",
            Dependencies.alias: ["//:t3"],
        },
        Address("", target_name="t1"),
    )
    t2 = PythonSourceTarget(
        {
            PythonSourceField.alias: "f.py",
            PythonResolveField.alias: "a",
            Dependencies.alias: ["//:t3"],
        },
        Address("", target_name="t2"),
    )
    t3 = PythonSourceTarget(
        {PythonSourceField.alias: "f.py", PythonResolveField.alias: "b"},
        Address("", target_name="t3"),
    )

    def maybe_get_resolve(t: Target) -> str | None:
        if not t.has_field(PythonResolveField):
            return None
        return t[PythonResolveField].normalized_value(python_setup)

    bad_roots_err = str(
        NoCompatibleResolveException.bad_input_roots(
            [t2, t3], maybe_get_resolve=maybe_get_resolve, doc_url_slug="", workaround=None
        )
    )
    assert bad_roots_err.startswith(
        softwrap(
            """
            The input targets did not have a resolve in common.

            a:
              * //:t2

            b:
              * //:t3

            Targets used together must use the same resolve, set by the `resolve` field.
            """
        )
    )

    bad_single_dep_err = str(
        NoCompatibleResolveException.bad_dependencies(
            maybe_get_resolve=maybe_get_resolve,
            doc_url_slug="",
            root_targets=[t1],
            root_resolve="a",
            dependencies=[t3],
        )
    )
    assert bad_single_dep_err.startswith(
        softwrap(
            """
            The target //:t1 uses the `resolve` `a`, but some of its
            dependencies are not compatible with that resolve:

              * //:t3 (b)

            All dependencies must work with the same `resolve`. To fix this, either change
            the `resolve=` field on those dependencies to `a`, or change
            the `resolve=` of the target //:t1.
            """
        )
    )

    bad_multiple_deps_err = str(
        NoCompatibleResolveException.bad_dependencies(
            maybe_get_resolve=maybe_get_resolve,
            doc_url_slug="",
            root_targets=[t1, t2],
            root_resolve="a",
            dependencies=[t3],
        )
    )
    assert bad_multiple_deps_err.startswith(
        softwrap(
            """
            The input targets use the `resolve` `a`, but some of their
            dependencies are not compatible with that resolve.

            Input targets:

              * //:t1
              * //:t2

            Bad dependencies:

              * //:t3 (b)

            All dependencies must work with the same `resolve`. To fix this, either change
            the `resolve=` field on those dependencies to `a`, or change
            the `resolve=` of the input targets.
            """
        )
    )


_default = "_default"


@pytest.mark.parametrize(
    ("env_names", "expected", "in_output", "not_in_output"),
    (
        ((), _default, None, "anything"),
        (("jeremy", "derek"), "jeremy", "`jeremy`, which may have ", None),
        (("jeremy", "_default"), "_default", "`_default`, which may have ", None),
        (("_default", "jeremy"), "_default", "`_default`, which may have ", None),
        (("jeremy",), "jeremy", None, "anything"),
    ),
)
def test_preferred_environment(
    env_names: Iterable[str],
    expected: str,
    in_output: str | None,
    not_in_output: str | None,
    caplog,
):
    resolve_name = "boop"
    resolve_dest = "beep"
    if not env_names:
        request = GenerateLockfile(resolve_name, resolve_dest, diff=False)
    else:
        envs = tuple(EnvironmentName(name) for name in env_names)
        request = GenerateLockfileWithEnvironments(
            resolve_name, resolve_dest, environments=envs, diff=False
        )

    default = EnvironmentName(_default)

    preferred_env = _preferred_environment(request, default)

    assert preferred_env.val == expected
    assert in_output is None or in_output in caplog.text
    assert not_in_output is None or not_in_output not in caplog.text


@pytest.mark.parametrize(
    "old_reqs, new_reqs, expect_diff",
    [
        ({}, dict(cowsay="5.0"), dict(added=dict(cowsay="5.0"))),
        (dict(cowsay="5.0"), {}, dict(removed=dict(cowsay="5.0"))),
        (dict(cowsay="4.0"), dict(cowsay="5.0"), dict(upgraded=dict(cowsay=("4.0", "5.0")))),
        (
            dict(cowsay="4.1.2"),
            dict(cowsay="4.1.1"),
            dict(downgraded=dict(cowsay=("4.1.2", "4.1.1"))),
        ),
        (dict(cowsay="4.1.2"), dict(cowsay="4.1.2"), dict(unchanged=dict(cowsay="4.1.2"))),
        (
            dict(prev="1.0", up_to_date="2.2", obsolete="x.y", mistake="2.0"),
            dict(prev="1.5", up_to_date="2.2", upcoming="y.x", mistake="1.9"),
            dict(
                added=dict(upcoming="y.x"),
                upgraded=dict(prev=("1.0", "1.5")),
                unchanged=dict(up_to_date="2.2"),
                removed=dict(obsolete="x.y"),
                downgraded=dict(mistake=("2.0", "1.9")),
            ),
        ),
    ],
)
def test_diff(
    old_reqs: Mapping[str, str], new_reqs: Mapping[str, str], expect_diff: Mapping[str, Any]
) -> None:
    diff = LockfileDiff.create(
        "reqs/test.lock",
        "testing",
        LockfilePackages(old_reqs),
        LockfilePackages(new_reqs),
    )
    assert {k: dict(v) for k, v in asdict(diff).items() if v and isinstance(v, Mapping)} == {
        k: v for k, v in expect_diff.items() if v
    }


@pytest.mark.parametrize(
    "old_reqs, new_reqs, expect_output",
    [
        (
            dict(prev="1.0", up_to_date="2.2", obsolete="x.y", mistake="2.0"),
            dict(prev="1.5", up_to_date="2.2", upcoming="y.x", mistake="1.9"),
            softwrap(
                """\
                Lockfile diff: reqs/test.lock [testing]

                ==                    Unchanged dependencies                    ==

                  up_to_date                     2.2

                ==                    Upgraded dependencies                     ==

                  prev                           1.0          -->   1.5

                ==                !! Downgraded dependencies !!                 ==

                  mistake                        2.0          -->   1.9

                ==                      Added dependencies                      ==

                  upcoming                       y.x

                ==                     Removed dependencies                     ==

                  obsolete                       x.y
                """
            ),
        )
    ],
)
def test_diff_printer(
    old_reqs: Mapping[str, str], new_reqs: Mapping[str, str], expect_output: str
) -> None:
    console = Mock(spec_set=Console)
    diff_formatter = LockfileDiffPrinter(console=console, color=False, include_unchanged=True)
    diff = LockfileDiff.create(
        "reqs/test.lock",
        "testing",
        LockfilePackages(old_reqs),
        LockfilePackages(new_reqs),
    )
    diff_formatter.print(diff)
    call = console.print_stderr.mock_calls[0]
    args = call[1]  # For py3.7 compat, otherwise `call.args` works.
    actual_output = softwrap(
        # Strip all spaces before newlines.
        re.sub(" +\n", "\n", args[0])
    )
    assert actual_output == expect_output


class TestExportableTool(ExportableTool):
    options_scope = "test_exportable_tool"


def test_filter_unconfigured_tools_configured():
    """Test that a configured tool succeeds."""
    resolve_name = "myresolve"
    resolve_dest = "resolve.lock"

    errs, results = filter_lockfiles_for_unconfigured_exportable_tools(
        [GenerateLockfile(resolve_name=resolve_name, lockfile_dest=resolve_dest, diff=False)],
        {resolve_name: TestExportableTool},
        resolve_specified=True,
    )

    assert len(errs) == 0
    assert len(results) == 1


def test_filter_unconfigured_tools_not_configured():
    """Test that a request for a tool using a default lockfiles results in an error."""
    resolve_name = "myresolve"
    resolve_dest = DEFAULT_TOOL_LOCKFILE

    errs, results = filter_lockfiles_for_unconfigured_exportable_tools(
        [GenerateLockfile(resolve_name=resolve_name, lockfile_dest=resolve_dest, diff=False)],
        {resolve_name: TestExportableTool},
        resolve_specified=True,
    )

    assert len(errs) == 1
    assert len(results) == 0


def test_filter_unconfigured_tools_all_excludes_internal():
    """Test that when a user requests all lockfiles, we exclude unconfigured internal tools."""
    resolve_name = "myresolve"
    resolve_dest = DEFAULT_TOOL_LOCKFILE

    errs, results = filter_lockfiles_for_unconfigured_exportable_tools(
        [GenerateLockfile(resolve_name=resolve_name, lockfile_dest=resolve_dest, diff=False)],
        {resolve_name: TestExportableTool},
        resolve_specified=False,
    )

    assert len(errs) == 0
    assert len(results) == 0
