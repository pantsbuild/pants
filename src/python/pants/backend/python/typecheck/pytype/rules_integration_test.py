# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from textwrap import dedent
from typing import Iterable

import pytest

from pants.backend.python import target_types_rules
from pants.backend.python.target_types import (
    PythonRequirementTarget,
    PythonSourcesGeneratorTarget,
    PythonSourceTarget,
)
from pants.backend.python.typecheck.pytype.rules import (
    PytypeFieldSet,
    PytypePartition,
    PytypePartitions,
    PytypeRequest,
)
from pants.backend.python.typecheck.pytype.rules import rules as pytype_rules
from pants.backend.python.util_rules.interpreter_constraints import InterpreterConstraints
from pants.core.goals.check import CheckResult, CheckResults
from pants.engine.addresses import Address
from pants.engine.fs import EMPTY_DIGEST
from pants.engine.rules import QueryRule
from pants.engine.target import Target
from pants.testutil.python_rule_runner import PythonRuleRunner


@pytest.fixture
def rule_runner() -> PythonRuleRunner:
    return PythonRuleRunner(
        rules=[
            *pytype_rules(),
            *target_types_rules.rules(),
            QueryRule(CheckResults, (PytypeRequest,)),
            QueryRule(PytypePartitions, (PytypeRequest,)),
        ],
        target_types=[
            PythonRequirementTarget,
            PythonSourcesGeneratorTarget,
            PythonSourceTarget,
        ],
    )


PACKAGE = "src/py/project"
GOOD_FILE = dedent(
    """\
    def add(x: int, y: int) -> int:
        return x + y

    result = add(3, 3)
    """
)
BAD_FILE = dedent(
    """\
    def add(x: int, y: int) -> int:
        return x + y

    result = add(2.0, 3.0)
    """
)
# This will fail if `name-error` is enabled (default).
NAME_ERROR_FILE = dedent(
    """\
    print(foo)
    """
)

NAME_ERROR_PYTYPE_CONFIG = dedent(
    """\
    [tool.pytype]

    disable = [
        'name-error',
    ]
    """
)


def run_pytype(
    rule_runner: PythonRuleRunner, targets: list[Target], *, extra_args: Iterable[str] | None = None
) -> tuple[CheckResult, ...]:
    rule_runner.set_options(extra_args or (), env_inherit={"PATH", "PYENV_ROOT", "HOME"})
    result = rule_runner.request(
        CheckResults, [PytypeRequest(PytypeFieldSet.create(tgt) for tgt in targets)]
    )

    return result.results


def test_passing(rule_runner: PythonRuleRunner) -> None:
    rule_runner.write_files({f"{PACKAGE}/f.py": GOOD_FILE, f"{PACKAGE}/BUILD": "python_sources()"})
    tgt = rule_runner.get_target(Address(PACKAGE, relative_file_path="f.py"))
    result = run_pytype(rule_runner, [tgt])

    assert len(result) == 1
    assert result[0].exit_code == 0
    assert "no errors found" in result[0].stdout
    assert result[0].report == EMPTY_DIGEST


def test_failing(rule_runner: PythonRuleRunner) -> None:
    rule_runner.write_files({f"{PACKAGE}/f.py": BAD_FILE, f"{PACKAGE}/BUILD": "python_sources()"})
    tgt = rule_runner.get_target(Address(PACKAGE, relative_file_path="f.py"))
    result = run_pytype(rule_runner, [tgt])

    assert len(result) == 1
    assert result[0].exit_code == 1
    assert "FAILED:" in result[0].stdout
    assert f'{PACKAGE}/f.py", line 4' in result[0].stdout
    assert result[0].report == EMPTY_DIGEST


def test_multiple_targets(rule_runner: PythonRuleRunner) -> None:
    rule_runner.write_files(
        {
            f"{PACKAGE}/good.py": GOOD_FILE,
            f"{PACKAGE}/bad.py": BAD_FILE,
            f"{PACKAGE}/BUILD": "python_sources()",
        }
    )
    tgts = [
        rule_runner.get_target(Address(PACKAGE, relative_file_path="good.py")),
        rule_runner.get_target(Address(PACKAGE, relative_file_path="bad.py")),
    ]
    result = run_pytype(rule_runner, tgts)

    assert len(result) == 1
    assert result[0].exit_code == 1
    assert f"{PACKAGE}/good.py" not in result[0].stdout
    assert f'{PACKAGE}/bad.py", line 4' in result[0].stdout
    assert "Analyzing 2 sources" in result[0].stdout
    assert result[0].report == EMPTY_DIGEST


@pytest.mark.parametrize(
    "config_filename,exit_code,extra_args",
    (
        ("pytype.toml", 0, ["--pytype-config=pytype.toml"]),
        ("pyproject.toml", 0, None),
        ("noconfig", 1, None),
    ),
)
def test_config_file(
    rule_runner: PythonRuleRunner,
    config_filename: str,
    exit_code: int,
    extra_args: Iterable[str] | None,
) -> None:
    rule_runner.write_files(
        {
            f"{PACKAGE}/f.py": NAME_ERROR_FILE,
            f"{PACKAGE}/BUILD": "python_sources()",
            f"{config_filename}": NAME_ERROR_PYTYPE_CONFIG,
        }
    )
    tgt = rule_runner.get_target(Address(PACKAGE, relative_file_path="f.py"))
    result = run_pytype(rule_runner, [tgt], extra_args=extra_args)

    assert len(result) == 1
    assert result[0].exit_code == exit_code


def test_skip(rule_runner: PythonRuleRunner) -> None:
    rule_runner.write_files({f"{PACKAGE}/f.py": BAD_FILE, f"{PACKAGE}/BUILD": "python_sources()"})
    tgt = rule_runner.get_target(Address(PACKAGE, relative_file_path="f.py"))
    result = run_pytype(rule_runner, [tgt], extra_args=["--pytype-skip"])

    assert not result


def test_partition_targets(rule_runner: PythonRuleRunner) -> None:
    def create_folder(folder: str, resolve: str, interpreter: str) -> dict[str, str]:
        return {
            f"{folder}/dep.py": "",
            f"{folder}/root.py": "",
            f"{folder}/BUILD": dedent(
                f"""\
                python_source(
                    name='dep',
                    source='dep.py',
                    resolve='{resolve}',
                    interpreter_constraints=['=={interpreter}.*'],
                )
                python_source(
                    name='root',
                    source='root.py',
                    resolve='{resolve}',
                    interpreter_constraints=['=={interpreter}.*'],
                    dependencies=[':dep'],
                )
                """
            ),
        }

    files = {
        **create_folder("resolveA_py38", "a", "3.8"),
        **create_folder("resolveA_py39", "a", "3.9"),
        **create_folder("resolveB_1", "b", "3.9"),
        **create_folder("resolveB_2", "b", "3.9"),
    }
    rule_runner.write_files(files)
    rule_runner.set_options(
        ["--python-resolves={'a': '', 'b': ''}", "--python-enable-resolves"],
        env_inherit={"PATH", "PYENV_ROOT", "HOME"},
    )

    resolve_a_py38_dep = rule_runner.get_target(Address("resolveA_py38", target_name="dep"))
    resolve_a_py38_root = rule_runner.get_target(Address("resolveA_py38", target_name="root"))
    resolve_a_py39_dep = rule_runner.get_target(Address("resolveA_py39", target_name="dep"))
    resolve_a_py39_root = rule_runner.get_target(Address("resolveA_py39", target_name="root"))
    resolve_b_dep1 = rule_runner.get_target(Address("resolveB_1", target_name="dep"))
    resolve_b_root1 = rule_runner.get_target(Address("resolveB_1", target_name="root"))
    resolve_b_dep2 = rule_runner.get_target(Address("resolveB_2", target_name="dep"))
    resolve_b_root2 = rule_runner.get_target(Address("resolveB_2", target_name="root"))
    request = PytypeRequest(
        PytypeFieldSet.create(t)
        for t in (
            resolve_a_py38_root,
            resolve_a_py39_root,
            resolve_b_root1,
            resolve_b_root2,
        )
    )

    partitions = rule_runner.request(PytypePartitions, [request])
    assert len(partitions) == 3

    def assert_partition(
        partition: PytypePartition,
        roots: list[Target],
        deps: list[Target],
        interpreter: str,
        resolve: str,
    ) -> None:
        root_addresses = {t.address for t in roots}
        assert {fs.address for fs in partition.field_sets} == root_addresses
        assert {t.address for t in partition.root_targets.closure()} == {
            *root_addresses,
            *(t.address for t in deps),
        }
        ics = [f"CPython=={interpreter}.*"]
        assert partition.interpreter_constraints == InterpreterConstraints(ics)
        assert partition.description() == f"{resolve}, {ics}"

    assert_partition(partitions[0], [resolve_a_py38_root], [resolve_a_py38_dep], "3.8", "a")
    assert_partition(partitions[1], [resolve_a_py39_root], [resolve_a_py39_dep], "3.9", "a")
    assert_partition(
        partitions[2],
        [resolve_b_root1, resolve_b_root2],
        [resolve_b_dep1, resolve_b_dep2],
        "3.9",
        "b",
    )
