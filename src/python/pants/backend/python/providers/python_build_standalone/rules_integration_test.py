# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import shutil
from textwrap import dedent
from typing import Iterable

import pytest

from pants.backend.python import target_types_rules
from pants.backend.python.dependency_inference import rules as dependency_inference_rules
from pants.backend.python.goals.run_python_source import PythonSourceFieldSet
from pants.backend.python.goals.run_python_source import rules as run_rules
from pants.backend.python.providers.python_build_standalone import rules as pbs
from pants.backend.python.providers.python_build_standalone.constraints import ConstraintsList
from pants.backend.python.target_types import PythonSourcesGeneratorTarget
from pants.backend.python.util_rules.interpreter_constraints import InterpreterConstraints
from pants.build_graph.address import Address
from pants.core.goals.run import RunRequest
from pants.core.util_rules.external_tool import ExternalToolError
from pants.engine.platform import Platform
from pants.engine.process import InteractiveProcess
from pants.engine.rules import QueryRule
from pants.engine.target import Target
from pants.testutil.option_util import create_subsystem
from pants.testutil.rule_runner import RuleRunner, mock_console
from pants.version import Version


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *run_rules(),
            *pbs.rules(),
            *dependency_inference_rules.rules(),
            *target_types_rules.rules(),
            QueryRule(RunRequest, (PythonSourceFieldSet,)),
            QueryRule(Platform, ()),
            QueryRule(pbs.PBSPythonProviderSubsystem, ()),
        ],
        target_types=[
            PythonSourcesGeneratorTarget,
        ],
    )


@pytest.fixture
def mock_empty_versions_resource():
    before = pbs.load_pbs_pythons
    pbs.load_pbs_pythons = lambda: {}
    yield
    pbs.load_pbs_pythons = before


def run_run_request(
    rule_runner: RuleRunner,
    target: Target,
    additional_args: Iterable[str] = (),
) -> str:
    args = [
        "--backend-packages=['pants.backend.python', 'pants.backend.python.providers.experimental.python_build_standalone']",
        "--source-root-patterns=['src']",
        *additional_args,
    ]
    rule_runner.set_options(args, env_inherit={"PATH", "PYENV_ROOT", "HOME"})
    run_request = rule_runner.request(RunRequest, [PythonSourceFieldSet.create(target)])
    run_process = InteractiveProcess(
        argv=run_request.args,
        env=run_request.extra_env,
        input_digest=run_request.digest,
        run_in_workspace=True,
        immutable_input_digests=run_request.immutable_input_digests,
        append_only_caches=run_request.append_only_caches,
    )
    with mock_console(rule_runner.options_bootstrapper) as mocked_console:
        rule_runner.run_interactive_process(run_process)
        return mocked_console[1].get_stdout().strip()


@pytest.mark.platform_specific_behavior
@pytest.mark.parametrize("py_version", ["3.8.*", "3.9.*", "3.9.10"])
def test_using_pbs(rule_runner, py_version):
    rule_runner.write_files(
        {
            "src/app.py": dedent(
                """\
                import sys

                print(sys.version.replace("\\n", " "))
                """
            ),
            "src/BUILD": f"python_sources(interpreter_constraints=['=={py_version}'])",
        }
    )

    target = rule_runner.get_target(Address("src", relative_file_path="app.py"))
    stdout = run_run_request(rule_runner, target)
    version = stdout.splitlines()[0]
    assert py_version.rstrip("*") in version
    # NB: The earliest 3.9 we support is 3.9.6, but that should never get chosen unless explicitly
    # requested because we should prefer latest-patch if possible.
    assert not version.startswith("3.9.6")


def test_useful_error(rule_runner):
    rule_runner.write_files(
        {
            "src/app.py": "",
            "src/BUILD": "python_sources(interpreter_constraints=['==2.7'])",
        }
    )

    target = rule_runner.get_target(Address("src", relative_file_path="app.py"))
    with pytest.raises(Exception, match="Supported versions are currently"):
        run_run_request(rule_runner, target)


def test_additional_versions(rule_runner, mock_empty_versions_resource):
    rule_runner.write_files(
        {
            "src/app.py": dedent(
                """\
                import sys

                print(sys.version.replace("\\n", " "))
                """
            ),
            "src/BUILD": "python_sources(interpreter_constraints=['==3.9.*'])",
        }
    )

    target = rule_runner.get_target(Address("src", relative_file_path="app.py"))
    with pytest.raises(Exception, match=r"Supported versions are currently: \[\]"):
        run_run_request(rule_runner, target)

    stdout = run_run_request(
        rule_runner,
        target,
        additional_args=[
            "--python-build-standalone-python-provider-known-python-versions=["
            + "'3.9.16|linux_arm64|75f3d10ae8933e17bf27e8572466ff8a1e7792f521d33acba578cc8a25d82e0b|24540128|https://github.com/indygreg/python-build-standalone/releases/download/20221220/cpython-3.9.16%2B20221220-aarch64-unknown-linux-gnu-install_only.tar.gz',"
            + "'3.9.16|macos_arm64|73bad3a610a0ff14166fbd5045cd186084bd2ce99edd2c6327054509e790b9ab|16765350|https://github.com/indygreg/python-build-standalone/releases/download/20221220/cpython-3.9.16%2B20221220-aarch64-apple-darwin-install_only.tar.gz',"
            + "'3.9.16|linux_x86_64|f885f3d011ab08e4d9521a7ae2662e9e0073acc0305a1178984b5a1cf057309a|26767987|https://github.com/indygreg/python-build-standalone/releases/download/20221220/cpython-3.9.16%2B20221220-x86_64-unknown-linux-gnu-install_only.tar.gz',"
            + "'3.9.16|macos_x86_64|69331e93656b179fcbfec0d506dfca11d899fe5dced990b28915e41755ce215c|17151321|https://github.com/indygreg/python-build-standalone/releases/download/20221220/cpython-3.9.16%2B20221220-x86_64-apple-darwin-install_only.tar.gz',"
            + "]"
        ],
    )
    version = stdout.splitlines()[0]
    assert version.startswith("3.9.16")


# Confirm whether the PBS tag data can be inferred from a URL.
def test_tag_inference_from_url() -> None:
    subsystem = create_subsystem(
        pbs.PBSPythonProviderSubsystem,
        known_python_versions=[
            "3.10.13|linux_arm64|e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855|123|https://github.com/indygreg/python-build-standalone/releases/download/20240224/cpython-3.10.13%2B20240224-aarch64-unknown-linux-gnu-install_only.tar.gz",
        ],
    )

    user_supplied_pbs_versions = subsystem.get_user_supplied_pbs_pythons()
    assert user_supplied_pbs_versions["3.10.13"]["20240224"]["linux_arm64"] == pbs.PBSPythonInfo(
        url="https://github.com/indygreg/python-build-standalone/releases/download/20240224/cpython-3.10.13%2B20240224-aarch64-unknown-linux-gnu-install_only.tar.gz",
        sha256="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        size=123,
    )

    # Confirm whether requiring tag inference results in an error.
    subsystem = create_subsystem(
        pbs.PBSPythonProviderSubsystem,
        known_python_versions=[
            "3.10.13|linux_arm64|e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855|123|file:///releases/20240224/cpython.tar.gz",
        ],
    )
    with pytest.raises(
        ExternalToolError, match="no PBS release tag could be inferred from the URL"
    ):
        _ = subsystem.get_user_supplied_pbs_pythons()


def test_venv_pex_reconstruction(rule_runner):
    """A VenvPex refers to the location of the venv so it doesn't have to re-construct if it exists.

    Part of this location is a hash of the interpreter. Without careful consideration it can be easy
    for this hash to drift from build-time to run-time. This test validates the assumption that the
    venv could be reconstructed exactly if the underlying directory was wiped clean.
    """
    rule_runner.write_files(
        {
            "src/app.py": dedent(
                """\
                import pathlib
                import sys

                in_venv_python_path = pathlib.Path(sys.executable)
                venv_link = in_venv_python_path.parent.parent
                venv_location = venv_link.resolve()
                print(venv_location)
                """
            ),
            "src/BUILD": "python_sources(interpreter_constraints=['==3.9.*'])",
        }
    )

    target = rule_runner.get_target(Address("src", relative_file_path="app.py"))
    stdout1 = run_run_request(rule_runner, target)
    assert "pex_root/venvs/" in stdout1
    venv_location = stdout1
    shutil.rmtree(venv_location)
    stdout2 = run_run_request(rule_runner, target)
    assert stdout1 == stdout2


def test_release_constraint_evaluation(rule_runner: RuleRunner) -> None:
    ics = InterpreterConstraints(["cpython==3.9.*"])
    universe = ["3.9"]

    def make_platform_metadata():
        return {
            "linux_arm64": {
                "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
                "size": 1,
                "url": "foobar",
            },
            "linux_x86_64": {
                "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
                "size": 1,
                "url": "https://example.com/foo.zip",
            },
            "macos_arm64": {
                "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
                "size": 1,
                "url": "https://example.com/foo.zip",
            },
            "macos_x86_64": {
                "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
                "size": 1,
                "url": "https://example.com/foo.zip",
            },
        }

    pbs_versions = {
        "3.9.18": {"20241001": make_platform_metadata()},
        "3.9.19": {"20241101": make_platform_metadata()},
        "3.9.20": {"20241201": make_platform_metadata()},
    }

    platform = rule_runner.request(Platform, [])

    rc = ConstraintsList.parse(">=20241001,<20241201")
    version, pbs_version, _info = pbs._choose_python(ics, universe, pbs_versions, platform, rc)
    assert version == "3.9.19"
    assert pbs_version == Version("20241101")

    # Ensure that exception occurs if no version matches.
    rc = ConstraintsList.parse("==20250101")
    with pytest.raises(
        Exception,
        match="Failed to find a supported Python Build Standalone for Interpreter Constraint",
    ):
        _version, _pbs_version, _info = pbs._choose_python(
            ics, universe, pbs_versions, platform, rc
        )

    # Ensure that PBS versions with no tag metadata are filtered out so there is no "match".
    actual_pbs_versions = pbs.load_pbs_pythons()
    rc = ConstraintsList.parse("==19700101")
    with pytest.raises(
        Exception,
        match="Failed to find a supported Python Build Standalone for Interpreter Constraint",
    ):
        _version, _pbs_version, _info = pbs._choose_python(
            ics, universe, actual_pbs_versions, platform, rc
        )

    # Ensure that the highest release for a particualr version is chosen.
    pbs_versions = {
        "3.9.18": {"20241001": make_platform_metadata()},
        "3.9.19": {"20241101": make_platform_metadata(), "20241115": make_platform_metadata()},
        "3.10.15": {"20241115": make_platform_metadata()},
    }
    rc = ConstraintsList.parse(">=20241001,<=20241201")
    version, pbs_version, _info = pbs._choose_python(ics, universe, pbs_versions, platform, rc)
    assert version == "3.9.19"
    assert pbs_version == Version("20241115")
