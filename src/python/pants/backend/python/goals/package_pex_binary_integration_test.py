# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import json
import os.path
import pkgutil
import subprocess
from dataclasses import dataclass
from textwrap import dedent
from typing import cast

import pytest

from pants.backend.python import target_types_rules
from pants.backend.python.goals import package_dists, package_pex_binary
from pants.backend.python.goals.package_pex_binary import (
    PexBinaryFieldSet,
    PexFromTargetsRequestForBuiltPackage,
)
from pants.backend.python.macros.python_artifact import PythonArtifact
from pants.backend.python.providers.python_build_standalone import rules as pbs
from pants.backend.python.target_types import (
    PexBinary,
    PexLayout,
    PythonDistribution,
    PythonRequirementTarget,
    PythonSourcesGeneratorTarget,
)
from pants.backend.python.util_rules import pex_from_targets
from pants.build_graph.address import Address
from pants.core.goals.package import BuiltPackage, BuiltPackageArtifact
from pants.core.target_types import (
    FilesGeneratorTarget,
    FileTarget,
    RelocatedFiles,
    ResourcesGeneratorTarget,
)
from pants.core.target_types import rules as core_target_types_rules
from pants.engine.internals.scheduler import ExecutionError
from pants.testutil.python_interpreter_selection import skip_unless_python38_present
from pants.testutil.python_rule_runner import PythonRuleRunner
from pants.testutil.rule_runner import QueryRule
from pants.testutil.skip_utils import skip_if_linux_arm64


def sorted_artifact_paths(artifacts: tuple[BuiltPackageArtifact, ...]) -> list[str]:
    relpaths = [a.relpath for a in artifacts]
    assert None not in relpaths
    return sorted(cast(list[str], relpaths))


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
        (
            expected_pex_relpath
            if PexLayout.ZIPAPP is layout
            else os.path.join(expected_pex_relpath, "__main__.py")
        ),
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


@skip_if_linux_arm64
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


def test_package_with_python_provider() -> None:
    # Per https://github.com/pantsbuild/pants/issues/21048, test packaging a local/unconstrained pex
    # binary when using a Python that isn't automatically visible on $PATH (using the PBS provider
    # as just one way to get such a Python)

    rule_runner = PythonRuleRunner(
        rules=[
            *package_pex_binary.rules(),
            *pex_from_targets.rules(),
            *target_types_rules.rules(),
            *core_target_types_rules(),
            *pbs.rules(),
            QueryRule(BuiltPackage, [PexBinaryFieldSet]),
        ],
        target_types=[
            PexBinary,
            PythonSourcesGeneratorTarget,
        ],
    )

    rule_runner.write_files(
        {
            "app.py": "",
            "BUILD": dedent(
                """\
                python_sources(name="src")
                pex_binary(name="target", entry_point="./app.py")
                """
            ),
        }
    )

    tgt = rule_runner.get_target(Address("", target_name="target"))
    field_set = PexBinaryFieldSet.create(tgt)

    # a random (https://xkcd.com/221/) old version of Python, that seems unlikely to be installed on
    # most systems, by default... but also, we don't propagate PATH (etc.) for this rule_runner, so
    # the test shouldn't be able to find system interpreters anyway.
    #
    # (Thus we have two layers of "assurance" the test is doing what is intended.)
    rule_runner.set_options(["--python-interpreter-constraints=CPython==3.10.2"])

    result = rule_runner.request(BuiltPackage, [field_set])
    assert len(result.artifacts) == 1
    assert result.artifacts[0].relpath == "target.pex"


def test_scie_defaults(rule_runner: PythonRuleRunner) -> None:
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
                    scie="lazy",
                    scie_pbs_release="20251031",  # The last release that includes Python 3.9.
                )
                """
            ),
        }
    )
    tgt = rule_runner.get_target(Address("src/py/project"))
    field_set = PexBinaryFieldSet.create(tgt)
    result = rule_runner.request(BuiltPackage, [field_set])
    assert (
        result.artifacts[0].relpath == "src.py.project/project.pex"
    )  # PEX must be first invariant
    assert sorted(
        ("src.py.project/project.pex", "src.py.project/project")
    ) == sorted_artifact_paths(result.artifacts)


@pytest.mark.parametrize("scie_hash_alg", ["md5", "sha1", "sha256", "sha384", "sha512"])
def test_scie_hash_present(rule_runner: PythonRuleRunner, scie_hash_alg: str) -> None:
    rule_runner.write_files(
        {
            "src/py/project/app.py": dedent(
                """\
                print("hello")
                """
            ),
            "src/py/project/BUILD": dedent(
                f"""\
                python_sources(name="lib")
                pex_binary(
                    entry_point="app.py",
                    scie="lazy",
                    scie_hash_alg="{scie_hash_alg}",
                    scie_pbs_release="20251031",  # The last release that includes Python 3.9.
                )
                """
            ),
        }
    )
    tgt = rule_runner.get_target(Address("src/py/project"))
    field_set = PexBinaryFieldSet.create(tgt)
    result = rule_runner.request(BuiltPackage, [field_set])
    assert sorted(
        (
            "src.py.project/project.pex",
            "src.py.project/project",
            f"src.py.project/project.{scie_hash_alg}",
        )
    ) == sorted_artifact_paths(result.artifacts)


def test_scie_platform_file_suffix(rule_runner: PythonRuleRunner) -> None:
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
                    scie="lazy",
                    scie_name_style="platform-file-suffix",
                    scie_platform=["linux-aarch64", "linux-x86_64"],
                    scie_pbs_release="20251031",  # The last release that includes Python 3.9.
                )
                """
            ),
        }
    )
    tgt = rule_runner.get_target(Address("src/py/project"))
    field_set = PexBinaryFieldSet.create(tgt)
    result = rule_runner.request(BuiltPackage, [field_set])
    assert sorted(
        (
            "src.py.project/project.pex",
            "src.py.project/project-linux-aarch64",
            "src.py.project/project-linux-x86_64",
        )
    ) == sorted_artifact_paths(result.artifacts)


def test_scie_platform_parent_dir(rule_runner: PythonRuleRunner) -> None:
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
                    scie="lazy",
                    scie_name_style="platform-parent-dir",
                    scie_platform=["linux-aarch64", "linux-x86_64"],
                    scie_pbs_release="20251031",  # The last release that includes Python 3.9.
                )
                """
            ),
        }
    )
    tgt = rule_runner.get_target(Address("src/py/project"))
    field_set = PexBinaryFieldSet.create(tgt)
    result = rule_runner.request(BuiltPackage, [field_set])
    assert sorted(
        (
            "src.py.project/project.pex",
            "src.py.project/linux-aarch64/project",
            "src.py.project/linux-x86_64/project",
        )
    ) == sorted_artifact_paths(result.artifacts)
    # The result is to directories, materialize to look inside and make sure
    # the right files are there
    rule_runner.write_digest(result.digest)
    os.path.exists(os.path.join(rule_runner.build_root, "src.py.project/linux-aarch64/project"))
    os.path.exists(os.path.join(rule_runner.build_root, "src.py.project/linux-x86_64/project"))


@pytest.mark.parametrize(
    "passthrough",
    [
        "",
        "scie_pex_entrypoint_env_passthrough=True,",
        "scie_pex_entrypoint_env_passthrough=False,",
    ],
)
def test_scie_busybox_moo(rule_runner: PythonRuleRunner, passthrough: str) -> None:
    rule_runner.write_files(
        {
            "src/py/project/app.py": dedent(
                """\
                print("hello")
                """
            ),
            "src/py/project/BUILD": dedent(
                f"""\
                python_sources(name="lib")
                python_requirement(name="cowsay", requirements=["cowsay==6.1"])
                pex_binary(
                    scie="lazy",
                    scie_pbs_release="20251031",  # The last release that includes Python 3.9.
                    dependencies=[":cowsay"],
                    scie_busybox='@',
                    {passthrough}
                )
                """
            ),
        }
    )
    tgt = rule_runner.get_target(Address("src/py/project"))
    field_set = PexBinaryFieldSet.create(tgt)
    result = rule_runner.request(BuiltPackage, [field_set])
    # Just asserting the right files are there to avoid downloading the whole
    # PBS during testing
    assert sorted(
        ("src.py.project/project.pex", "src.py.project/project")
    ) == sorted_artifact_paths(result.artifacts)


def test_scie_pbs_version(rule_runner: PythonRuleRunner) -> None:
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
                python_requirement(name="cowsay", requirements=["cowsay==6.1"])
                pex_binary(
                    entry_point="app.py",
                    scie="lazy",
                    scie_pbs_release="20241219"
                )
                """
            ),
        }
    )
    tgt = rule_runner.get_target(Address("src/py/project"))
    field_set = PexBinaryFieldSet.create(tgt)
    result = rule_runner.request(BuiltPackage, [field_set])
    # Just asserting the right files are there to avoid downloading the whole
    # PBS during testing
    assert sorted(
        ("src.py.project/project.pex", "src.py.project/project")
    ) == sorted_artifact_paths(result.artifacts)


def test_scie_python_version_available(rule_runner: PythonRuleRunner) -> None:
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
                    scie="lazy",
                    scie_pbs_release="20251031",
                    scie_python_version="3.12.12"
                )
                """
            ),
        }
    )
    tgt = rule_runner.get_target(Address("src/py/project"))
    field_set = PexBinaryFieldSet.create(tgt)
    result = rule_runner.request(BuiltPackage, [field_set])
    # Just asserting the right files are there to avoid downloading the whole
    # PBS during testing
    assert sorted(
        ("src.py.project/project.pex", "src.py.project/project")
    ) == sorted_artifact_paths(result.artifacts)


def test_scie_python_version_unavailable(rule_runner: PythonRuleRunner) -> None:
    # The PBS project does not produce binaries for every patch release
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
                    scie="lazy",
                    scie_pbs_release="20251031",
                    scie_python_version="3.12.2"
                )
                """
            ),
        }
    )
    tgt = rule_runner.get_target(Address("src/py/project"))
    field_set = PexBinaryFieldSet.create(tgt)
    with pytest.raises(
        ExecutionError, match="No released assets found for release 20251031 Python 3.12.2"
    ):
        rule_runner.request(BuiltPackage, [field_set])


@pytest.mark.parametrize(
    "stripped",
    [
        "",
        "scie_pbs_stripped=True,",
        "scie_pbs_stripped=False,",
    ],
)
def test_scie_pbs_stripped(rule_runner: PythonRuleRunner, stripped: str) -> None:
    rule_runner.write_files(
        {
            "src/py/project/app.py": dedent(
                """\
                print("hello")
                """
            ),
            "src/py/project/BUILD": dedent(
                f"""\
                python_sources(name="lib")
                python_requirement(name="cowsay", requirements=["cowsay==6.1"])
                pex_binary(
                    scie="lazy",
                    scie_pbs_release="20251031",  # The last release that includes Python 3.9.
                    dependencies=[":cowsay"],
                    scie_busybox='@',
                    {stripped}
                )
                """
            ),
        }
    )
    tgt = rule_runner.get_target(Address("src/py/project"))
    field_set = PexBinaryFieldSet.create(tgt)
    result = rule_runner.request(BuiltPackage, [field_set])
    # Just asserting the right files are there to avoid downloading the whole
    # PBS during testing
    assert sorted(
        ("src.py.project/project.pex", "src.py.project/project")
    ) == sorted_artifact_paths(result.artifacts)


@pytest.mark.parametrize("scie_load_dotenv", [True, False])
def test_scie_load_dotenv_passthru(rule_runner: PythonRuleRunner, scie_load_dotenv: bool) -> None:
    rule_runner.write_files(
        {
            "src/py/project/app.py": dedent(
                """\
                print("hello")
                """
            ),
            "src/py/project/BUILD": dedent(
                f"""\
                python_sources(name="lib")
                pex_binary(
                    entry_point="app.py",
                    scie="lazy",
                    scie_load_dotenv={scie_load_dotenv},
                    scie_pbs_release="20251031",  # The last release that includes Python 3.9.
                )
                """
            ),
        }
    )
    tgt = rule_runner.get_target(Address("src/py/project"))
    field_set = PexBinaryFieldSet.create(tgt)
    result = rule_runner.request(BuiltPackage, [field_set])
    # Just asserting that this executes, but not re-checking Pex's implementation
    assert len(result.artifacts) == 2
    assert "src.py.project/project.pex" == result.artifacts[0].relpath


def test_scie_pbs_free_threaded(rule_runner: PythonRuleRunner) -> None:
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
                    scie="lazy",
                    scie_python_version="3.14.2",
                    scie_pbs_free_threaded=True,
                    scie_pbs_release="20251205",  # With free threaded and 3.14.2
                )
                """
            ),
        }
    )
    tgt = rule_runner.get_target(Address("src/py/project"))
    field_set = PexBinaryFieldSet.create(tgt)
    result = rule_runner.request(BuiltPackage, [field_set])
    rule_runner.write_digest(result.digest)
    executable = os.path.join(rule_runner.build_root, "src.py.project/project")
    output = subprocess.check_output(executable, env={"SCIE": "inspect"})
    # Minimal check without brittle binding to the exact SCIE=inspect format
    # Will look something like 'ptex':
    # {'cpython-3.14.2+20251205-x86_64-unknown-linux-gnu-freethreaded+pgo+lto-full.tar.zst':
    # 'https://github.com/astral-sh/python-build-standalone/releases/download/20251205/cpython-3.14.2%2B20251205-x86_64-unknown-linux-gnu-freethreaded%2Bpgo%2Blto-full.tar.zst'}}
    assert b"freethreaded" in output


def test_scie_pbs_debug(rule_runner: PythonRuleRunner) -> None:
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
                    scie="lazy",
                    scie_pbs_debug=True,
                    scie_pbs_release="20251031",  # The last release that includes Python 3.9.
                )
                """
            ),
        }
    )
    tgt = rule_runner.get_target(Address("src/py/project"))
    field_set = PexBinaryFieldSet.create(tgt)
    result = rule_runner.request(BuiltPackage, [field_set])

    rule_runner.write_digest(result.digest)
    executable = os.path.join(rule_runner.build_root, "src.py.project/project")
    output = subprocess.check_output(executable, env={"SCIE": "inspect"})
    assert b"stripped" not in output


def test_scie_with_local_dist(rule_runner: PythonRuleRunner) -> None:
    # This is a regression test for a bug early in adding scie support where
    # the --requirements-pex flag was lost when building a scie pex, causing
    # local distributions to not be included in the final executable.
    rule_runner.write_files(
        {
            "lib/__init__.py": "",
            "lib/greeting.py": dedent(
                """\
                def get_greeting():
                    return "Hello from local dist!"
                """
            ),
            "lib/BUILD": dedent(
                """\
                python_sources(name="sources")

                python_distribution(
                    name="dist",
                    dependencies=[":sources"],
                    provides=python_artifact(
                        name="guten-tag-lib",
                        version="0.0.1",
                    ),
                )
                """
            ),
            "app/main.py": dedent(
                """\
                from lib.greeting import get_greeting

                if __name__ == "__main__":
                    print(get_greeting())
                """
            ),
            "app/BUILD": dedent(
                """\
                python_sources(name="sources")

                pex_binary(
                    name="app",
                    entry_point="main.py",
                    dependencies=[":sources", "lib:dist"],
                    scie="eager",  # Going to run it, so might as well
                    scie_pbs_release="20251031",
                )
                """
            ),
        }
    )
    tgt = rule_runner.get_target(Address("app", target_name="app"))
    field_set = PexBinaryFieldSet.create(tgt)
    result = rule_runner.request(BuiltPackage, [field_set])

    rule_runner.write_digest(result.digest)
    executable = os.path.join(rule_runner.build_root, "app/app")

    output = subprocess.check_output([executable], text=True)
    assert "Hello from local dist!" in output


def test_scie_custom_exe_with_env_and_args(rule_runner: PythonRuleRunner) -> None:
    # Test that scie_exe, scie_args, and scie_env work together correctly.
    # The script path comes from scie_bind_resource_path -> scie_env -> scie_exe,
    # and an argument value comes from scie_env -> scie_args.
    rule_runner.write_files(
        {
            "src/py/project/print_argv.py": dedent(
                """\
                import os
                import sys

                print("ARGV:" + repr(sys.argv[1:]))
                print("GREETING:" + os.environ.get("GREETING", "NOT_SET"))
                """
            ),
            "src/py/project/BUILD": dedent(
                """\
                python_sources(name="lib")
                pex_binary(
                    entry_point="print_argv.py",
                    scie="eager",
                    scie_pbs_release="20251031",
                    # Bind the script's resource path to MY_SCRIPT env var
                    scie_bind_resource_path=["MY_SCRIPT=project/print_argv.py"],
                    # Set env vars: GREETING will be used in scie_args
                    scie_env=["GREETING=hello_world"],
                    # Use the venv's Python as the executable
                    scie_exe="{scie.env.VIRTUAL_ENV}/bin/python",
                    # Pass the script path and the greeting as args
                    scie_args=["{scie.env.MY_SCRIPT}", "--message", "{scie.env.GREETING}"],
                )
                """
            ),
        }
    )
    tgt = rule_runner.get_target(Address("src/py/project"))
    field_set = PexBinaryFieldSet.create(tgt)
    result = rule_runner.request(BuiltPackage, [field_set])

    rule_runner.write_digest(result.digest)
    executable = os.path.join(rule_runner.build_root, "src.py.project/project")
    output = subprocess.check_output([executable], text=True)

    # Verify the script received the args from scie_args (with scie_env substitution)
    assert "ARGV:" in output
    assert "'--message'" in output
    assert "'hello_world'" in output
    # Verify the GREETING env var was set by scie_env
    assert "GREETING:hello_world" in output
