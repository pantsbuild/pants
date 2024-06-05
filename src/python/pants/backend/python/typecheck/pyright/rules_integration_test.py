# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import json
from textwrap import dedent
from typing import Iterable

import pytest

from pants.backend.javascript.package_json import PackageJsonTarget
from pants.backend.python import target_types_rules
from pants.backend.python.target_types import (
    PythonRequirementTarget,
    PythonSourcesGeneratorTarget,
    PythonSourceTarget,
)
from pants.backend.python.typecheck.pyright.rules import (
    PyrightFieldSet,
    PyrightPartition,
    PyrightPartitions,
    PyrightRequest,
)
from pants.backend.python.typecheck.pyright.rules import rules as pyright_rules
from pants.backend.python.util_rules.interpreter_constraints import InterpreterConstraints
from pants.core.goals.check import CheckResult, CheckResults
from pants.engine.addresses import Address
from pants.engine.fs import EMPTY_DIGEST
from pants.engine.rules import QueryRule
from pants.engine.target import Target
from pants.testutil.python_interpreter_selection import skip_unless_all_pythons_present
from pants.testutil.python_rule_runner import PythonRuleRunner
from pants.util.contextutil import temporary_dir
from pants.util.dirutil import safe_rmtree


@pytest.fixture
def rule_runner() -> PythonRuleRunner:
    return PythonRuleRunner(
        rules=[
            *pyright_rules(),
            *target_types_rules.rules(),
            QueryRule(CheckResults, (PyrightRequest,)),
            QueryRule(PyrightPartitions, (PyrightRequest,)),
        ],
        target_types=[
            PythonRequirementTarget,
            PythonSourcesGeneratorTarget,
            PythonSourceTarget,
            PackageJsonTarget,
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
# This will fail if `reportUndefinedVariable` is enabled (default).
UNDEFINED_VARIABLE_FILE = dedent(
    """\
    print(foo)
    """
)

UNDEFINED_VARIABLE_JSON_CONFIG = dedent(
    """\
    {
        "reportUndefinedVariable": false
    }
    """
)

UNDEFINED_VARIABLE_TOML_CONFIG = dedent(
    """\
    [tool.pyright]
    reportUndefinedVariable = false
    """
)

PYRIGHT_VERSION = "1.1.365"
PYRIGHT_LOCKFILE = json.dumps(
    {
        "name": "@the-company/project",
        "lockfileVersion": 2,
        "requires": True,
        "packages": {
            "": {"name": "@the-company/project", "devDependencies": {"pyright": PYRIGHT_VERSION}},
            "node_modules/pyright": {
                "version": PYRIGHT_VERSION,
                "resolved": f"https://registry.npmjs.org/pyright/-/pyright-{PYRIGHT_VERSION}.tgz",
                "integrity": "sha512-Pdb9AwOO07uNOuEVtwCThyDpB0wigWmLjeCw5vdPG7gVbVYYgY2iw64kBdwTu78NrO0igVKzmoRuApMoL6ZE0w==",
                "dev": True,
                "bin": {"pyright": "index.js", "pyright-langserver": "langserver.index.js"},
                "engines": {"node": ">=12.0.0"},
            },
        },
        "dependencies": {
            "pyright": {
                "version": PYRIGHT_VERSION,
                "resolved": f"https://registry.npmjs.org/pyright/-/pyright-{PYRIGHT_VERSION}.tgz",
                "integrity": "sha512-Pdb9AwOO07uNOuEVtwCThyDpB0wigWmLjeCw5vdPG7gVbVYYgY2iw64kBdwTu78NrO0igVKzmoRuApMoL6ZE0w==",
                "dev": True,
            }
        },
    }
)


def run_pyright(
    rule_runner: PythonRuleRunner, targets: list[Target], *, extra_args: Iterable[str] | None = None
) -> tuple[CheckResult, ...]:
    rule_runner.set_options(extra_args or (), env_inherit={"PATH", "PYENV_ROOT", "HOME"})
    result = rule_runner.request(
        CheckResults, [PyrightRequest(PyrightFieldSet.create(tgt) for tgt in targets)]
    )
    return result.results


def test_passing(rule_runner: PythonRuleRunner) -> None:
    rule_runner.write_files({f"{PACKAGE}/f.py": GOOD_FILE, f"{PACKAGE}/BUILD": "python_sources()"})
    tgt = rule_runner.get_target(Address(PACKAGE, relative_file_path="f.py"))
    result = run_pyright(rule_runner, [tgt])
    assert len(result) == 1
    assert result[0].exit_code == 0
    assert "0 errors" in result[0].stdout
    assert result[0].report == EMPTY_DIGEST


def test_failing(rule_runner: PythonRuleRunner) -> None:
    rule_runner.write_files({f"{PACKAGE}/f.py": BAD_FILE, f"{PACKAGE}/BUILD": "python_sources()"})
    tgt = rule_runner.get_target(Address(PACKAGE, relative_file_path="f.py"))
    result = run_pyright(rule_runner, [tgt])
    assert len(result) == 1
    assert result[0].exit_code == 1
    assert f"{PACKAGE}/f.py:4" in result[0].stdout
    assert "2 errors" in result[0].stdout
    assert result[0].report == EMPTY_DIGEST


def test_multiple_targets(rule_runner: PythonRuleRunner) -> None:
    rule_runner.write_files(
        {
            f"{PACKAGE}/bad1.py": BAD_FILE,
            f"{PACKAGE}/bad2.py": BAD_FILE,
            f"{PACKAGE}/BUILD": "python_sources()",
        }
    )
    tgts = [
        rule_runner.get_target(Address(PACKAGE, relative_file_path="bad1.py")),
        rule_runner.get_target(Address(PACKAGE, relative_file_path="bad2.py")),
    ]
    result = run_pyright(rule_runner, tgts)
    assert len(result) == 1
    assert result[0].exit_code == 1
    assert f"{PACKAGE}/bad1.py:4" in result[0].stdout
    assert f"{PACKAGE}/bad2.py:4" in result[0].stdout
    assert "4 errors" in result[0].stdout
    assert result[0].report == EMPTY_DIGEST


@pytest.mark.parametrize(
    "config_filename,config_file,exit_code",
    (
        ("pyrightconfig.json", UNDEFINED_VARIABLE_JSON_CONFIG, 0),
        ("pyproject.toml", UNDEFINED_VARIABLE_TOML_CONFIG, 0),
        ("noconfig", "", 1),
    ),
)
def test_config_file(
    rule_runner: PythonRuleRunner, config_filename: str, config_file: str, exit_code: int
) -> None:
    rule_runner.write_files(
        {
            f"{PACKAGE}/f.py": UNDEFINED_VARIABLE_FILE,
            f"{PACKAGE}/BUILD": "python_sources()",
            f"{config_filename}": config_file,
        }
    )
    tgt = rule_runner.get_target(Address(PACKAGE, relative_file_path="f.py"))
    result = run_pyright(rule_runner, [tgt])
    assert len(result) == 1
    assert result[0].exit_code == exit_code


LIB_1_PACKAGE = f"{PACKAGE}/lib1"
LIB_2_PACKAGE = f"{PACKAGE}/lib2"


@pytest.mark.parametrize(
    "files, extra_args",
    [
        pytest.param(
            {
                f"{LIB_1_PACKAGE}/core/a.py": GOOD_FILE,
                f"{LIB_1_PACKAGE}/core/BUILD": "python_sources()",
                f"{LIB_2_PACKAGE}/core/b.py": "from core.a import add",
                f"{LIB_2_PACKAGE}/core/BUILD": "python_sources()",
            },
            (f"--source-root-patterns=['{LIB_1_PACKAGE}', '{LIB_2_PACKAGE}']",),
            id="from_version",
        ),
        pytest.param(
            {
                f"{LIB_1_PACKAGE}/core/a.py": GOOD_FILE,
                f"{LIB_1_PACKAGE}/core/BUILD": "python_sources()",
                f"{LIB_2_PACKAGE}/core/b.py": "from core.a import add",
                f"{LIB_2_PACKAGE}/core/BUILD": "python_sources()",
                "src/js/lib3/BUILD": "package_json()",
                "src/js/lib3/package.json": json.dumps(
                    {"name": "@the-company/project", "dependencies": {"pyright": PYRIGHT_VERSION}}
                ),
                "src/js/lib3/package-lock.json": PYRIGHT_LOCKFILE,
            },
            (
                f"--source-root-patterns=['{LIB_1_PACKAGE}', '{LIB_2_PACKAGE}', 'src/js']",
                "--pyright-install-from-resolve=lib3",
            ),
            id="from_resolve",
        ),
        pytest.param(
            {
                f"{LIB_1_PACKAGE}/core/a.py": GOOD_FILE,
                f"{LIB_1_PACKAGE}/core/BUILD": "python_sources()",
                f"{LIB_2_PACKAGE}/core/b.py": "from core.a import add",
                f"{LIB_2_PACKAGE}/core/BUILD": "python_sources()",
                "BUILD": "package_json(name='root_package')",
                "package.json": json.dumps(
                    {"name": "@the-company/project", "dependencies": {"pyright": PYRIGHT_VERSION}}
                ),
                "package-lock.json": PYRIGHT_LOCKFILE,
            },
            (
                f"--source-root-patterns=['{LIB_1_PACKAGE}', '{LIB_2_PACKAGE}', '/']",
                "--pyright-install-from-resolve=nodejs-default",
            ),
            id="from_resolve_at_root",
        ),
    ],
)
def test_additional_source_roots(
    files: dict[str, str], extra_args: tuple[str, ...], rule_runner: PythonRuleRunner
) -> None:
    rule_runner.write_files(files)
    tgts = [
        rule_runner.get_target(Address(f"{LIB_1_PACKAGE}/core", relative_file_path="a.py")),
        rule_runner.get_target(Address(f"{LIB_2_PACKAGE}/core", relative_file_path="b.py")),
    ]
    result = run_pyright(rule_runner, tgts)
    assert len(result) == 1
    assert result[0].exit_code == 1
    assert "reportMissingImports" in result[0].stdout

    result = run_pyright(
        rule_runner,
        tgts,
        extra_args=extra_args,
    )
    assert len(result) == 1
    assert result[0].exit_code == 0

    # When we run on just one target, Pyright should find its dependency in the other source root.
    result = run_pyright(
        rule_runner,
        tgts[1:],
        extra_args=extra_args,
    )
    assert len(result) == 1
    assert result[0].exit_code == 0


def test_skip(rule_runner: PythonRuleRunner) -> None:
    rule_runner.write_files({f"{PACKAGE}/f.py": BAD_FILE, f"{PACKAGE}/BUILD": "python_sources()"})
    tgt = rule_runner.get_target(Address(PACKAGE, relative_file_path="f.py"))
    result = run_pyright(rule_runner, [tgt], extra_args=["--pyright-skip"])
    assert not result


def test_passing_cache_clear(rule_runner: PythonRuleRunner) -> None:
    # Ensure that the requirements venv must be created, by adding in a third-party
    # requirement to the test code.
    rule_runner.write_files(
        {
            "BUILD": "python_requirement(name='more-itertools', requirements=['more-itertools==8.4.0'])",
            f"{PACKAGE}/f.py": dedent(
                """\
            from more_itertools import is_sorted

            assert is_sorted([1, 2, 3]) is True
            """
            ),
            f"{PACKAGE}/BUILD": "python_sources()",
        }
    )
    tgt = rule_runner.get_target(Address(PACKAGE, relative_file_path="f.py"))

    with temporary_dir() as cache_dir:
        # On the first run, Pyright should work as the venv will be created from scratch.
        result = run_pyright(rule_runner, [tgt], extra_args=[f"--named-caches-dir={cache_dir}"])
        assert len(result) == 1
        assert result[0].exit_code == 0
        assert "0 errors" in result[0].stdout
        assert result[0].report == EMPTY_DIGEST

        # Delete the cache directory containing the venv
        safe_rmtree(cache_dir)

        # Run again - should work as the venv will be created again from scratch.
        result = run_pyright(rule_runner, [tgt], extra_args=[f"--named-caches-dir={cache_dir}"])
        assert len(result) == 1
        assert result[0].exit_code == 0
        assert "0 errors" in result[0].stdout
        assert result[0].report == EMPTY_DIGEST


@pytest.mark.parametrize(
    "files, extra_args",
    [
        pytest.param(
            {
                "BUILD": (
                    "python_requirement(name='more-itertools', requirements=['more-itertools==8.4.0'])"
                ),
                f"{PACKAGE}/f.py": dedent(
                    """\
            from more_itertools import flatten

            assert flatten(42) == [4, 2]
            """
                ),
                f"{PACKAGE}/BUILD": "python_sources()",
            },
            (),
            id="from_version",
        ),
        pytest.param(
            {
                "BUILD": (
                    "python_requirement(name='more-itertools', requirements=['more-itertools==8.4.0'])"
                ),
                f"{PACKAGE}/f.py": dedent(
                    """\
                from more_itertools import flatten

                assert flatten(42) == [4, 2]
                """
                ),
                f"{PACKAGE}/BUILD": "python_sources()",
                "src/js/BUILD": "package_json()",
                "src/js/package.json": json.dumps(
                    {"name": "@the-company/project", "dependencies": {"pyright": PYRIGHT_VERSION}}
                ),
                "src/js/package-lock.json": PYRIGHT_LOCKFILE,
            },
            ("--pyright-install-from-resolve=js",),
            id="from_resolve",
        ),
    ],
)
def test_thirdparty_dependency(
    rule_runner: PythonRuleRunner, files: dict[str, str], extra_args: tuple[str, ...]
) -> None:
    rule_runner.write_files(files)
    tgt = rule_runner.get_target(Address(PACKAGE, relative_file_path="f.py"))
    result = run_pyright(rule_runner, [tgt], extra_args=extra_args)
    assert len(result) == 1
    assert result[0].exit_code == 1
    assert f"{PACKAGE}/f.py:3" in result[0].stdout


@skip_unless_all_pythons_present("3.8", "3.9")
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
    request = PyrightRequest(
        PyrightFieldSet.create(t)
        for t in (
            resolve_a_py38_root,
            resolve_a_py39_root,
            resolve_b_root1,
            resolve_b_root2,
        )
    )

    partitions = rule_runner.request(PyrightPartitions, [request])
    assert len(partitions) == 3

    def assert_partition(
        partition: PyrightPartition,
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
