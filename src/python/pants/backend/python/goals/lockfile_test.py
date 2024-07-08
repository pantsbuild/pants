# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import json
from textwrap import dedent

import pytest

from pants.backend.python.goals.lockfile import (
    GeneratePythonLockfile,
    RequestedPythonUserResolveNames,
)
from pants.backend.python.goals.lockfile import rules as lockfile_rules
from pants.backend.python.goals.lockfile import setup_user_lockfile_requests
from pants.backend.python.subsystems.setup import RESOLVE_OPTION_KEY__DEFAULT, PythonSetup
from pants.backend.python.target_types import PythonRequirementTarget
from pants.backend.python.util_rules import pex
from pants.backend.python.util_rules.interpreter_constraints import InterpreterConstraints
from pants.core.goals.generate_lockfiles import GenerateLockfileResult, UserGenerateLockfiles
from pants.engine.fs import DigestContents
from pants.engine.internals.scheduler import ExecutionError
from pants.testutil.python_rule_runner import PythonRuleRunner
from pants.testutil.rule_runner import PYTHON_BOOTSTRAP_ENV, QueryRule
from pants.util.ordered_set import FrozenOrderedSet
from pants.util.strutil import strip_prefix


@pytest.fixture
def rule_runner() -> PythonRuleRunner:
    rule_runner = PythonRuleRunner(
        rules=[
            *lockfile_rules(),
            *pex.rules(),
            QueryRule(GenerateLockfileResult, [GeneratePythonLockfile]),
        ]
    )
    rule_runner.set_options([], env_inherit=PYTHON_BOOTSTRAP_ENV)
    return rule_runner


def _generate(
    *,
    rule_runner: PythonRuleRunner,
    requirements_string: str = "ansicolors==1.1.8",
    requirement_constraints_str: str = '//   "requirement_constraints": [],\n',
    only_binary_and_no_binary_str: str = '//   "only_binary": [],\n//   "no_binary": []',
) -> str:
    result = rule_runner.request(
        GenerateLockfileResult,
        [
            GeneratePythonLockfile(
                requirements=FrozenOrderedSet([requirements_string] if requirements_string else []),
                find_links=FrozenOrderedSet([]),
                interpreter_constraints=InterpreterConstraints(),
                resolve_name="test",
                lockfile_dest="test.lock",
                diff=False,
            )
        ],
    )
    digest_contents = rule_runner.request(DigestContents, [result.digest])
    assert len(digest_contents) == 1
    content = digest_contents[0].content.decode()

    pex_header = (
        dedent(
            f"""\
            // This lockfile was autogenerated by Pants. To regenerate, run:
            //
            //    pants generate-lockfiles --resolve=test
            //
            // --- BEGIN PANTS LOCKFILE METADATA: DO NOT EDIT OR REMOVE ---
            // {{
            //   "version": 3,
            //   "valid_for_interpreter_constraints": [],
            //   "generated_with_requirements": [
            //     "{requirements_string}"
            //   ],
            //   "manylinux": "manylinux2014",
            """
        )
        + requirement_constraints_str
        + only_binary_and_no_binary_str
        + dedent(
            """
            // }
            // --- END PANTS LOCKFILE METADATA ---
            """
        )
    )
    assert content.startswith(pex_header)
    return strip_prefix(content, pex_header)


@pytest.mark.parametrize(
    ("no_binary", "only_binary"), ((False, False), (False, True), (True, False))
)
def test_pex_lockfile_generation(
    rule_runner: PythonRuleRunner, no_binary: bool, only_binary: bool
) -> None:
    args = ["--python-resolves={'test': 'foo.lock'}"]
    only_binary_lock_str = '//   "only_binary": [],\n'
    no_binary_lock_str = '//   "no_binary": []'
    no_binary_arg = f"{{'{RESOLVE_OPTION_KEY__DEFAULT}': ['ansicolors']}}"
    if no_binary:
        no_binary_lock_str = dedent(
            """\
            //   "no_binary": [
            //     "ansicolors"
            //   ]"""
        )
        args.append(f"--python-resolves-to-no-binary={no_binary_arg}")
    if only_binary:
        only_binary_lock_str = dedent(
            """\
            //   "only_binary": [
            //     "ansicolors"
            //   ],
            """
        )
        args.append(f"--python-resolves-to-only-binary={no_binary_arg}")
    rule_runner.set_options(args, env_inherit=PYTHON_BOOTSTRAP_ENV)

    lock_entry = json.loads(
        _generate(
            rule_runner=rule_runner,
            only_binary_and_no_binary_str=only_binary_lock_str + no_binary_lock_str,
        )
    )
    reqs = lock_entry["locked_resolves"][0]["locked_requirements"]
    assert len(reqs) == 1
    assert reqs[0]["project_name"] == "ansicolors"
    assert reqs[0]["version"] == "1.1.8"

    wheel = {
        "algorithm": "sha256",
        "hash": "00d2dde5a675579325902536738dd27e4fac1fd68f773fe36c21044eb559e187",
        "url": (
            "https://files.pythonhosted.org/packages/53/18/"
            + "a56e2fe47b259bb52201093a3a9d4a32014f9d85071ad07e9d60600890ca/"
            + "ansicolors-1.1.8-py2.py3-none-any.whl"
        ),
    }
    sdist = {
        "algorithm": "sha256",
        "hash": "99f94f5e3348a0bcd43c82e5fc4414013ccc19d70bd939ad71e0133ce9c372e0",
        "url": (
            "https://files.pythonhosted.org/packages/76/31/"
            + "7faed52088732704523c259e24c26ce6f2f33fbeff2ff59274560c27628e/"
            + "ansicolors-1.1.8.zip"
        ),
    }

    artifacts = reqs[0]["artifacts"]

    if not no_binary and not only_binary:
        # Don't assume that the order in artifacts is deterministic.
        # We can't just convert to a set because dicts aren't hashable.
        assert len(artifacts) == 2
        assert wheel in artifacts
        assert sdist in artifacts
    elif no_binary:
        assert artifacts == [sdist]
    elif only_binary:
        assert artifacts == [wheel]


def test_constraints_file(rule_runner: PythonRuleRunner) -> None:
    rule_runner.write_files({"constraints.txt": "ansicolors==1.1.7"})
    rule_runner.set_options(
        [
            "--python-resolves={'test': 'foo.lock'}",
            f"--python-resolves-to-constraints-file={{'{RESOLVE_OPTION_KEY__DEFAULT}': 'constraints.txt'}}",
        ],
        env_inherit=PYTHON_BOOTSTRAP_ENV,
    )

    lock_entry = json.loads(
        _generate(
            rule_runner=rule_runner,
            requirements_string="ansicolors>=1.0",
            requirement_constraints_str=dedent(
                """\
                //   "requirement_constraints": [
                //     "ansicolors==1.1.7"
                //   ],
                """
            ),
        )
    )
    reqs = lock_entry["locked_resolves"][0]["locked_requirements"]
    assert len(reqs) == 1
    assert reqs[0]["project_name"] == "ansicolors"
    assert reqs[0]["version"] == "1.1.7"


def test_multiple_resolves() -> None:
    rule_runner = PythonRuleRunner(
        rules=[
            setup_user_lockfile_requests,
            *PythonSetup.rules(),
            QueryRule(UserGenerateLockfiles, [RequestedPythonUserResolveNames]),
        ],
        target_types=[PythonRequirementTarget],
    )
    rule_runner.write_files(
        {
            "BUILD": dedent(
                """\
                python_requirement(
                    name='a',
                    requirements=['a'],
                    resolve='a',
                )
                python_requirement(
                    name='b',
                    requirements=['b'],
                    resolve='b',
                )
                """
            ),
        }
    )
    rule_runner.set_options(
        [
            "--python-resolves={'a': 'a.lock', 'b': 'b.lock'}",
            # Override interpreter constraints for 'b', but use default for 'a'.
            "--python-resolves-to-interpreter-constraints={'b': ['==3.7.*']}",
            "--python-enable-resolves",
        ],
        env_inherit=PYTHON_BOOTSTRAP_ENV,
    )
    result = rule_runner.request(
        UserGenerateLockfiles, [RequestedPythonUserResolveNames(["a", "b"])]
    )
    assert set(result) == {
        GeneratePythonLockfile(
            requirements=FrozenOrderedSet(["a"]),
            find_links=FrozenOrderedSet([]),
            interpreter_constraints=InterpreterConstraints(["CPython>=3.7,<3.10"]),
            resolve_name="a",
            lockfile_dest="a.lock",
            diff=False,
        ),
        GeneratePythonLockfile(
            requirements=FrozenOrderedSet(["b"]),
            find_links=FrozenOrderedSet([]),
            interpreter_constraints=InterpreterConstraints(["==3.7.*"]),
            resolve_name="b",
            lockfile_dest="b.lock",
            diff=False,
        ),
    }


def test_empty_requirements(rule_runner: PythonRuleRunner) -> None:
    with pytest.raises(ExecutionError) as excinfo:
        json.loads(
            _generate(
                rule_runner=rule_runner,
                requirements_string="",
            )
        )

    assert (
        "Cannot generate lockfile with no requirements. Please add some requirements to test."
        in str(excinfo.value)
    )
