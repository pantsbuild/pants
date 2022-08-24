# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import textwrap

import pytest

from pants.backend.python.pip_requirement import PipRequirement
from pants.backend.python.subsystems.setup import InvalidLockfileBehavior, PythonSetup
from pants.backend.python.util_rules.interpreter_constraints import InterpreterConstraints
from pants.backend.python.util_rules.lockfile_metadata import PythonLockfileMetadataV3
from pants.backend.python.util_rules.pex_requirements import (
    Lockfile,
    ResolvePexConfig,
    ResolvePexConstraintsFile,
    ToolCustomLockfile,
    ToolDefaultLockfile,
    _pex_lockfile_requirement_count,
    _strip_comments_from_pex_json_lockfile,
    is_probably_pex_json_lockfile,
    should_validate_metadata,
    validate_metadata,
)
from pants.engine.fs import FileContent
from pants.engine.internals.native_engine import EMPTY_DIGEST
from pants.testutil.option_util import create_subsystem
from pants.util.ordered_set import FrozenOrderedSet

METADATA = PythonLockfileMetadataV3(
    InterpreterConstraints(["==3.8.*"]),
    {PipRequirement.parse("ansicolors"), PipRequirement.parse("requests")},
    manylinux=None,
    requirement_constraints={PipRequirement.parse("abc")},
    only_binary={PipRequirement.parse("bdist")},
    no_binary={PipRequirement.parse("sdist")},
)


def create_tool_lock(
    *,
    default_lock: bool = False,
    uses_source_plugins: bool = False,
    uses_project_interpreter_constraints: bool = False,
) -> ToolDefaultLockfile | ToolCustomLockfile:
    common_kwargs = dict(
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


def test_invalid_lockfile_behavior_option() -> None:
    """Test that you can toggle between warnings, errors, and ignoring."""

    assert not should_validate_metadata(
        create_tool_lock(), create_python_setup(InvalidLockfileBehavior.ignore)
    )
    assert should_validate_metadata(
        create_tool_lock(), create_python_setup(InvalidLockfileBehavior.warn)
    )
    assert should_validate_metadata(
        create_tool_lock(), create_python_setup(InvalidLockfileBehavior.error)
    )


@pytest.mark.parametrize(
    "is_default_lock,invalid_reqs,invalid_interpreter_constraints,invalid_constraints_file,"
    + "invalid_only_binary,invalid_no_binary,uses_source_plugins,uses_project_ic",
    [
        (
            is_default_lock,
            invalid_reqs,
            invalid_interpreter_constraints,
            invalid_constraints_file,
            invalid_only_binary,
            invalid_no_binary,
            source_plugins,
            project_ics,
        )
        for is_default_lock in (True, False)
        for invalid_reqs in (True, False)
        for invalid_interpreter_constraints in (True, False)
        for invalid_constraints_file in (True, False)
        for invalid_only_binary in (True, False)
        for invalid_no_binary in (True, False)
        for source_plugins in (True, False)
        for project_ics in (True, False)
        if (invalid_reqs or invalid_interpreter_constraints or invalid_constraints_file)
    ],
)
def test_validate_tool_lockfiles(
    is_default_lock: bool,
    invalid_reqs: bool,
    invalid_interpreter_constraints: bool,
    invalid_constraints_file: bool,
    invalid_only_binary: bool,
    invalid_no_binary: bool,
    uses_source_plugins: bool,
    uses_project_ic: bool,
    caplog,
) -> None:
    runtime_interpreter_constraints = (
        InterpreterConstraints(["==2.7.*"])
        if invalid_interpreter_constraints
        else METADATA.valid_for_interpreter_constraints
    )
    req_strings = ["bad-req"] if invalid_reqs else [str(r) for r in METADATA.requirements]
    requirements = create_tool_lock(
        default_lock=is_default_lock,
        uses_source_plugins=uses_source_plugins,
        uses_project_interpreter_constraints=uses_project_ic,
    )
    validate_metadata(
        METADATA,
        runtime_interpreter_constraints,
        requirements,
        req_strings,
        create_python_setup(InvalidLockfileBehavior.warn),
        ResolvePexConfig(
            indexes=("index",),
            find_links=("find-links",),
            manylinux=None,
            constraints_file=ResolvePexConstraintsFile(
                EMPTY_DIGEST,
                "c.txt",
                FrozenOrderedSet(
                    {PipRequirement.parse("xyz" if invalid_constraints_file else "abc")}
                ),
            ),
            no_binary=FrozenOrderedSet(
                [PipRequirement.parse("not-sdist" if invalid_no_binary else "sdist")]
            ),
            only_binary=FrozenOrderedSet(
                [PipRequirement.parse("not-bdist" if invalid_only_binary else "bdist")]
            ),
            path_mappings=(),
        ),
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

    contains("You have set interpreter constraints", if_=invalid_interpreter_constraints)
    contains(
        "determines its interpreter constraints based on your code's own constraints.",
        if_=invalid_interpreter_constraints and uses_project_ic,
    )
    contains(
        ".interpreter_constraints`, or by using a new custom lockfile.",
        if_=invalid_interpreter_constraints and not uses_project_ic,
    )

    contains("The constraints file at c.txt has changed", if_=invalid_constraints_file)
    contains("The `only_binary` arguments have changed", if_=invalid_only_binary)
    contains("The `no_binary` arguments have changed", if_=invalid_no_binary)

    contains(
        "To generate a custom lockfile based on your current configuration", if_=is_default_lock
    )
    contains(
        "To regenerate your lockfile based on your current configuration", if_=not is_default_lock
    )


@pytest.mark.parametrize(
    (
        "invalid_reqs,invalid_interpreter_constraints,invalid_constraints_file,invalid_only_binary,"
        + "invalid_no_binary,invalid_manylinux"
    ),
    [
        (
            invalid_reqs,
            invalid_interpreter_constraints,
            invalid_constraints_file,
            invalid_only_binary,
            invalid_no_binary,
            invalid_manylinux,
        )
        for invalid_reqs in (True, False)
        for invalid_interpreter_constraints in (True, False)
        for invalid_constraints_file in (True, False)
        for invalid_only_binary in (True, False)
        for invalid_no_binary in (True, False)
        for invalid_manylinux in (True, False)
        if (
            invalid_reqs
            or invalid_interpreter_constraints
            or invalid_constraints_file
            or invalid_only_binary
            or invalid_no_binary
            or invalid_manylinux
        )
    ],
)
def test_validate_user_lockfiles(
    invalid_reqs: bool,
    invalid_interpreter_constraints: bool,
    invalid_constraints_file: bool,
    invalid_only_binary: bool,
    invalid_no_binary: bool,
    invalid_manylinux: bool,
    caplog,
) -> None:
    runtime_interpreter_constraints = (
        InterpreterConstraints(["==2.7.*"])
        if invalid_interpreter_constraints
        else METADATA.valid_for_interpreter_constraints
    )
    req_strings = FrozenOrderedSet(
        ["bad-req"] if invalid_reqs else [str(r) for r in METADATA.requirements]
    )
    lockfile = Lockfile(
        file_path="lock.txt",
        file_path_description_of_origin="foo",
        resolve_name="a",
    )

    # Ignore validation if resolves are manually managed.
    assert not should_validate_metadata(
        lockfile, create_python_setup(InvalidLockfileBehavior.warn, enable_resolves=False)
    )

    validate_metadata(
        METADATA,
        runtime_interpreter_constraints,
        lockfile,
        req_strings,
        create_python_setup(InvalidLockfileBehavior.warn),
        ResolvePexConfig(
            indexes=(),
            find_links=(),
            manylinux="not-manylinux" if invalid_manylinux else None,
            constraints_file=ResolvePexConstraintsFile(
                EMPTY_DIGEST,
                "c.txt",
                FrozenOrderedSet(
                    {PipRequirement.parse("xyz" if invalid_constraints_file else "abc")}
                ),
            ),
            no_binary=FrozenOrderedSet(
                [PipRequirement.parse("not-sdist" if invalid_no_binary else "sdist")]
            ),
            only_binary=FrozenOrderedSet(
                [PipRequirement.parse("not-bdist" if invalid_only_binary else "bdist")]
            ),
            path_mappings=(),
        ),
    )

    def contains(msg: str, if_: bool = True) -> None:
        assert (msg in caplog.text) is if_

    contains("You are using the lockfile at lock.txt to install the resolve `a`")
    contains(
        "The targets depend on requirements that are not in the lockfile: ['bad-req']",
        if_=invalid_reqs,
    )

    contains("The targets use interpreter constraints", if_=invalid_interpreter_constraints)

    contains("The constraints file at c.txt has changed", if_=invalid_constraints_file)
    contains("The `only_binary` arguments have changed", if_=invalid_only_binary)
    contains("The `no_binary` arguments have changed", if_=invalid_no_binary)
    contains("The `manylinux` argument has changed", if_=invalid_manylinux)

    contains("./pants generate-lockfiles --resolve=a`")


def test_is_probably_pex_json_lockfile():
    def is_pex(lock: str) -> bool:
        return is_probably_pex_json_lockfile(lock.encode())

    for s in (
        "{}",
        textwrap.dedent(
            """\
            // Special comment
            {}
            """
        ),
        textwrap.dedent(
            """\
            // Next line has extra space
             {"key": "val"}
            """
        ),
        textwrap.dedent(
            """\
            {
                "key": "val",
            }
            """
        ),
    ):
        assert is_pex(s)

    for s in (
        "",
        "# foo",
        "# {",
        "cheesey",
        "cheesey==10.0",
        textwrap.dedent(
            """\
            # Special comment
            cheesey==10.0
            """
        ),
    ):
        assert not is_pex(s)


def test_strip_comments_from_pex_json_lockfile() -> None:
    def assert_stripped(lock: str, expected: str) -> None:
        assert _strip_comments_from_pex_json_lockfile(lock.encode()).decode() == expected

    assert_stripped("{}", "{}")
    assert_stripped(
        textwrap.dedent(
            """\
            { // comment
                "key": "foo",
            }
            """
        ),
        textwrap.dedent(
            """\
            { // comment
                "key": "foo",
            }"""
        ),
    )
    assert_stripped(
        textwrap.dedent(
            """\
            // header
               // more header
              {
                "key": "foo",
            }
            // footer
            """
        ),
        textwrap.dedent(
            """\
              {
                "key": "foo",
            }"""
        ),
    )


def test_pex_lockfile_requirement_count() -> None:
    assert _pex_lockfile_requirement_count(b"empty") == 2
    assert (
        _pex_lockfile_requirement_count(
            textwrap.dedent(
                """\
            {
              "allow_builds": true,
              "allow_prereleases": false,
              "allow_wheels": true,
              "build_isolation": true,
              "constraints": [],
              "locked_resolves": [
                {
                  "locked_requirements": [
                    {
                      "artifacts": [
                        {
                          "algorithm": "sha256",
                          "hash": "00d2dde5a675579325902536738dd27e4fac1fd68f773fe36c21044eb559e187",
                          "url": "https://files.pythonhosted.org/packages/53/18/a56e2fe47b259bb52201093a3a9d4a32014f9d85071ad07e9d60600890ca/ansicolors-1.1.8-py2.py3-none-any.whl"
                        }
                      ],
                      "project_name": "ansicolors",
                      "requires_dists": [],
                      "requires_python": null,
                      "version": "1.1.8"
                    }
                  ],
                  "platform_tag": [
                    "cp39",
                    "cp39",
                    "macosx_11_0_arm64"
                  ]
                }
              ],
              "pex_version": "2.1.70",
              "prefer_older_binary": false,
              "requirements": [
                "ansicolors"
              ],
              "requires_python": [],
              "resolver_version": "pip-legacy-resolver",
              "style": "strict",
              "transitive": true,
              "use_pep517": null
            }
            """
            ).encode()
        )
        == 3
    )
