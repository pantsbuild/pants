# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import json
import os.path
import pkgutil
import subprocess
from dataclasses import dataclass
from textwrap import dedent

import pytest

from pants.backend.python import target_types_rules
from pants.backend.python.goals import package_dists, package_pex_binary
from pants.backend.python.goals.package_pex_binary import (
    PexBinaryFieldSet,
    PexFromTargetsRequestForBuiltPackage,
)
from pants.backend.python.macros.python_artifact import PythonArtifact
from pants.backend.python.subsystems.setuptools import PythonDistributionFieldSet
from pants.backend.python.target_types import (
    PexBinary,
    PexLayout,
    PythonDistribution,
    PythonRequirementTarget,
    PythonSourcesGeneratorTarget,
)
from pants.backend.python.util_rules import pex_from_targets
from pants.build_graph.address import Address
from pants.core.goals.package import BuiltPackage
from pants.core.target_types import (
    FilesGeneratorTarget,
    FileTarget,
    RelocatedFiles,
    ResourcesGeneratorTarget,
)
from pants.core.target_types import rules as core_target_types_rules
from pants.testutil.python_interpreter_selection import skip_unless_python38_present
from pants.testutil.python_rule_runner import PythonRuleRunner
from pants.testutil.rule_runner import QueryRule


@pytest.fixture
def rule_runner() -> PythonRuleRunner:
    rule_runner = PythonRuleRunner(
        rules=[
            *package_pex_binary.rules(),
            *pex_from_targets.rules(),
            *target_types_rules.rules(),
            *core_target_types_rules(),
            *package_dists.rules(),
            QueryRule(BuiltPackage, [PexBinaryFieldSet]),
            QueryRule(PexFromTargetsRequestForBuiltPackage, [PexBinaryFieldSet]),
            QueryRule(BuiltPackage, [PythonDistributionFieldSet]),
        ],
        target_types=[
            FileTarget,
            FilesGeneratorTarget,
            PexBinary,
            PythonDistribution,
            PythonRequirementTarget,
            PythonSourcesGeneratorTarget,
            RelocatedFiles,
            ResourcesGeneratorTarget,
        ],
        objects={"python_artifact": PythonArtifact},
    )
    rule_runner.set_options([], env_inherit={"PATH", "PYENV_ROOT", "HOME"})
    return rule_runner


def test_warn_files_targets(rule_runner: PythonRuleRunner, caplog) -> None:
    rule_runner.write_files(
        {
            "assets/f.txt": "",
            "assets/BUILD": dedent(
                """\
                files(name='files', sources=['f.txt'])
                relocated_files(
                    name='relocated',
                    files_targets=[':files'],
                    src='assets',
                    dest='new_assets',
                )

                # Resources are fine.
                resources(name='resources', sources=['f.txt'])
                """
            ),
            "src/py/project/__init__.py": "",
            "src/py/project/app.py": "print('hello')",
            "src/py/project/BUILD": dedent(
                """\
                pex_binary(
                    dependencies=['assets:files', 'assets:relocated', 'assets:resources'],
                    entry_point="none",
                )
                """
            ),
        }
    )
    tgt = rule_runner.get_target(Address("src/py/project"))
    field_set = PexBinaryFieldSet.create(tgt)

    assert not caplog.records
    result = rule_runner.request(BuiltPackage, [field_set])
    assert caplog.records
    assert f"The target {tgt.address} (`pex_binary`) transitively depends on" in caplog.text
    assert "assets/f.txt:files" in caplog.text
    assert "assets:relocated" in caplog.text
    assert "assets:resources" not in caplog.text

    assert len(result.artifacts) == 1
    assert result.artifacts[0].relpath == "src.py.project/project.pex"


def test_include_sources_avoids_files_targets_warning(
    rule_runner: PythonRuleRunner, caplog
) -> None:
    rule_runner.write_files(
        {
            "assets/f.txt": "",
            "assets/BUILD": dedent(
                """\
                files(name='files', sources=['f.txt'])
                relocated_files(
                    name='relocated',
                    files_targets=[':files'],
                    src='assets',
                    dest='new_assets',
                )
                """
            ),
            "src/py/project/__init__.py": "",
            "src/py/project/app.py": "print('hello')",
            "src/py/project/BUILD": dedent(
                """\
                python_sources(
                    name='sources',
                    interpreter_constraints=["CPython==3.10.*"]
                )

                python_distribution(
                    name='wheel',
                    dependencies=[
                        ':sources',
                        'assets:relocated',
                    ],
                    provides=python_artifact(
                        name='my-dist',
                        version='1.2.3',
                    ),
                    interpreter_constraints=["CPython==3.10.*"]
                )

                pex_binary(
                    dependencies=[':wheel'],
                    entry_point="none",
                    include_sources=False,
                    interpreter_constraints=["CPython==3.10.*"]
                )
                """
            ),
        }
    )
    tgt = rule_runner.get_target(Address("src/py/project"))
    field_set = PexBinaryFieldSet.create(tgt)

    assert not caplog.records
    result = rule_runner.request(BuiltPackage, [field_set])
    assert not caplog.records

    assert len(result.artifacts) == 1
    assert result.artifacts[0].relpath == "src.py.project/project.pex"


@pytest.mark.parametrize(
    "layout",
    [pytest.param(layout, id=layout.value) for layout in PexLayout],
)
def test_layout(rule_runner: PythonRuleRunner, layout: PexLayout) -> None:
    rule_runner.write_files(
        {
            "src/py/project/app.py": dedent(
                """\
                import os
                import sys
                for env in ["FOO", "--inject-arg", "quotes '"]:
                    print(f"{env}={os.environ.get(env)}")
                print(f"ARGV={sys.argv[1:]}")
                """
            ),
            "src/py/project/BUILD": dedent(
                f"""\
                python_sources(name="lib")
                pex_binary(
                    entry_point="app.py",
                    args=['123', 'abc', '--inject-env', "quotes 'n spaces"],
                    env={{'FOO': 'xxx', '--inject-arg': 'yyy', "quotes '": 'n spaces'}},
                    layout="{layout.value}",
                )
                """
            ),
        }
    )
    tgt = rule_runner.get_target(Address("src/py/project"))
    field_set = PexBinaryFieldSet.create(tgt)
    result = rule_runner.request(BuiltPackage, [field_set])
    assert len(result.artifacts) == 1
    expected_pex_relpath = "src.py.project/project.pex"
    assert expected_pex_relpath == result.artifacts[0].relpath

    rule_runner.write_digest(result.digest)
    executable = os.path.join(
        rule_runner.build_root,
        expected_pex_relpath
        if PexLayout.ZIPAPP is layout
        else os.path.join(expected_pex_relpath, "__main__.py"),
    )
    stdout = dedent(
        """\
        FOO=xxx
        --inject-arg=yyy
        quotes '=n spaces
        ARGV=['123', 'abc', '--inject-env', "quotes 'n spaces"]
        """
    ).encode()
    assert stdout == subprocess.run([executable], check=True, stdout=subprocess.PIPE).stdout


@pytest.fixture
def pex_executable(rule_runner: PythonRuleRunner) -> str:
    rule_runner.write_files(
        {
            "pex_exe/BUILD": dedent(
                """\
                python_requirement(name="req", requirements=["pex==2.1.112"])
                pex_binary(dependencies=[":req"], script="pex")
                """
            ),
        }
    )
    tgt = rule_runner.get_target(Address("pex_exe"))
    field_set = PexBinaryFieldSet.create(tgt)
    result = rule_runner.request(BuiltPackage, [field_set])
    assert len(result.artifacts) == 1
    expected_pex_relpath = "pex_exe/pex_exe.pex"
    assert expected_pex_relpath == result.artifacts[0].relpath
    rule_runner.write_digest(result.digest)
    return os.path.join(rule_runner.build_root, expected_pex_relpath)


def test_resolve_local_platforms(pex_executable: str, rule_runner: PythonRuleRunner) -> None:
    complete_current_platform = subprocess.run(
        args=[pex_executable, "interpreter", "inspect", "-mt"],
        env=dict(PEX_MODULE="pex.cli", **os.environ),
        stdout=subprocess.PIPE,
    ).stdout

    # N.B.: ansicolors 1.0.2 is available sdist-only on PyPI, so resolving it requires using a
    # local interpreter.
    rule_runner.write_files(
        {
            "src/py/project/app.py": "import colors",
            "src/py/project/platform.json": complete_current_platform,
            "src/py/project/BUILD": dedent(
                """\
                python_requirement(name="ansicolors", requirements=["ansicolors==1.0.2"])
                file(name="platform", source="platform.json")
                pex_binary(
                    dependencies=[":ansicolors"],
                    complete_platforms=[":platform"],
                    resolve_local_platforms=True,
                )
                """
            ),
        }
    )
    tgt = rule_runner.get_target(Address("src/py/project"))
    field_set = PexBinaryFieldSet.create(tgt)
    result = rule_runner.request(BuiltPackage, [field_set])
    assert len(result.artifacts) == 1
    expected_pex_relpath = "src.py.project/project.pex"
    assert expected_pex_relpath == result.artifacts[0].relpath

    rule_runner.write_digest(result.digest)
    executable = os.path.join(rule_runner.build_root, expected_pex_relpath)
    subprocess.run([executable], check=True)


@skip_unless_python38_present
@pytest.mark.parametrize("target_type", ["files", "resources"])
def test_complete_platforms(rule_runner: PythonRuleRunner, target_type: str) -> None:
    linux_complete_platform = pkgutil.get_data(__name__, "platform-linux-py38.json")
    assert linux_complete_platform is not None

    mac_complete_platform = pkgutil.get_data(__name__, "platform-mac-py38.json")
    assert mac_complete_platform is not None

    rule_runner.write_files(
        {
            "src/py/project/platform-linux-py38.json": linux_complete_platform,
            "src/py/project/platform-mac-py38.json": mac_complete_platform,
            "src/py/project/BUILD": dedent(
                f"""\
                python_requirement(name="p537", requirements=["p537==1.0.6"])
                {target_type}(name="platforms", sources=["platform*.json"])
                pex_binary(
                    dependencies=[":p537"],
                    complete_platforms=[":platforms"],
                    include_tools=True,
                )
                """
            ),
        }
    )
    tgt = rule_runner.get_target(Address("src/py/project"))
    field_set = PexBinaryFieldSet.create(tgt)
    result = rule_runner.request(BuiltPackage, [field_set])
    assert len(result.artifacts) == 1
    expected_pex_relpath = "src.py.project/project.pex"
    assert expected_pex_relpath == result.artifacts[0].relpath

    rule_runner.write_digest(result.digest)
    executable = os.path.join(rule_runner.build_root, expected_pex_relpath)
    pex_info = json.loads(
        subprocess.run(
            args=[executable, "info"],
            env=dict(PEX_TOOLS="1", **os.environ),
            stdout=subprocess.PIPE,
            check=True,
        ).stdout
    )
    assert sorted(
        [
            "p537-1.0.6-cp38-cp38-manylinux_2_5_x86_64.manylinux1_x86_64.whl",
            "p537-1.0.6-cp38-cp38-macosx_10_15_x86_64.whl",
        ]
    ) == sorted(pex_info["distributions"])


def test_non_hermetic_venv_scripts(rule_runner: PythonRuleRunner) -> None:
    rule_runner.write_files(
        {
            "src/py/project/app.py": dedent(
                """\
                import json
                import os
                import sys


                json.dump(
                    {
                        "PYTHONPATH": os.environ.get("PYTHONPATH"),
                        "sys.path": sys.path,
                    },
                    sys.stdout,
                )
                """
            ),
            "src/py/project/BUILD": dedent(
                """\
                python_sources(name="app")

                pex_binary(
                    name="hermetic",
                    entry_point="app.py",
                    execution_mode="venv",
                    venv_hermetic_scripts=True,
                    dependencies=[
                        ":app",
                    ],
                )

                pex_binary(
                    name="non-hermetic",
                    entry_point="app.py",
                    execution_mode="venv",
                    venv_hermetic_scripts=False,
                    dependencies=[
                        ":app",
                    ],
                )
                """
            ),
        }
    )

    @dataclass(frozen=True)
    class Results:
        pythonpath: str | None
        sys_path: list[str]

    def execute_pex(address: Address, **extra_env) -> Results:
        tgt = rule_runner.get_target(address)
        field_set = PexBinaryFieldSet.create(tgt)
        result = rule_runner.request(BuiltPackage, [field_set])
        assert len(result.artifacts) == 1
        rule_runner.write_digest(result.digest)
        relpath = result.artifacts[0].relpath
        assert relpath is not None
        pex = os.path.join(rule_runner.build_root, relpath)
        assert os.path.isfile(pex)
        process = subprocess.run(
            args=[pex],
            env={**os.environ, **extra_env},
            cwd=rule_runner.build_root,
            stdout=subprocess.PIPE,
            check=True,
        )
        data = json.loads(process.stdout)
        return Results(pythonpath=data["PYTHONPATH"], sys_path=data["sys.path"])

    bob_sys_path_entry = os.path.join(rule_runner.build_root, "bob")

    hermetic_results = execute_pex(
        Address("src/py/project", target_name="hermetic"), PYTHONPATH="bob"
    )
    assert "bob" == hermetic_results.pythonpath
    assert bob_sys_path_entry not in hermetic_results.sys_path

    non_hermetic_results = execute_pex(
        Address("src/py/project", target_name="non-hermetic"), PYTHONPATH="bob"
    )
    assert "bob" == non_hermetic_results.pythonpath
    assert bob_sys_path_entry in non_hermetic_results.sys_path


def test_sh_boot_plumb(rule_runner: PythonRuleRunner) -> None:
    rule_runner.write_files(
        {
            "src/py/project/app.py": dedent(
                """\
                print("hello")
                """
            ),
            "src/py/project/BUILD": dedent(
                """\
                python_sources(name="lib")
                pex_binary(
                    entry_point="app.py",
                    sh_boot=True
                )
                """
            ),
        }
    )
    tgt = rule_runner.get_target(Address("src/py/project"))
    field_set = PexBinaryFieldSet.create(tgt)
    result = rule_runner.request(BuiltPackage, [field_set])
    assert len(result.artifacts) == 1
    expected_pex_relpath = "src.py.project/project.pex"
    assert expected_pex_relpath == result.artifacts[0].relpath

    rule_runner.write_digest(result.digest)

    executable = os.path.join(rule_runner.build_root, expected_pex_relpath)
    with open(executable, "rb") as f:
        shebang = f.readline().decode()
        assert "#!/bin/sh" in shebang


def test_extra_build_args(rule_runner: PythonRuleRunner) -> None:
    rule_runner.write_files(
        {
            "src/py/project/app.py": dedent(
                """\
                print("hello")
                """
            ),
            "src/py/project/BUILD": dedent(
                """\
                python_sources(name="lib")
                pex_binary(
                    entry_point="app.py",
                    extra_build_args=["--example-extra-arg", "value-goes-here"]
                )
                """
            ),
        }
    )

    tgt = rule_runner.get_target(Address("src/py/project"))
    field_set = PexBinaryFieldSet.create(tgt)
    result = rule_runner.request(PexFromTargetsRequestForBuiltPackage, [field_set])

    additional_args = result.request.additional_args

    assert additional_args[-2] == "--example-extra-arg"
    assert additional_args[-1] == "value-goes-here"
