# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import shutil
from textwrap import dedent

import pytest

from pants.backend.python import target_types_rules
from pants.backend.python.dependency_inference import rules as dependency_inference_rules
from pants.backend.python.goals.run_python_source import PythonSourceFieldSet
from pants.backend.python.goals.run_python_source import rules as run_rules
from pants.backend.python.providers.pyenv.rules import rules as pyenv_rules
from pants.backend.python.target_types import PythonSourcesGeneratorTarget
from pants.build_graph.address import Address
from pants.core.goals.run import RunRequest
from pants.engine.process import InteractiveProcess
from pants.engine.rules import QueryRule
from pants.engine.target import Target
from pants.testutil.rule_runner import RuleRunner, mock_console


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *run_rules(),
            *pyenv_rules(),
            *dependency_inference_rules.rules(),
            *target_types_rules.rules(),
            QueryRule(RunRequest, (PythonSourceFieldSet,)),
        ],
        target_types=[
            PythonSourcesGeneratorTarget,
        ],
    )


def run_run_request(
    rule_runner: RuleRunner,
    target: Target,
) -> str:
    args = [
        "--backend-packages=['pants.backend.python', 'pants.backend.python.providers.experimental.pyenv']",
        "--source-root-patterns=['src']",
        "--pyenv-python-provider-installation-extra-env-vars=['HOME']",
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


@pytest.mark.parametrize(
    "interpreter_constraints, expected_version_substring",
    [("2.7.*", "2.7"), ("3.9.*", "3.9"), ("3.10.4", "3.10.4")],
)
def test_using_pyenv(rule_runner, interpreter_constraints, expected_version_substring):
    rule_runner.write_files(
        {
            "src/app.py": dedent(
                """\
                import os.path
                import sys
                import sysconfig

                print(sysconfig.get_config_var("prefix"))
                print(sys.version.replace("\\n", " "))
                """
            ),
            "src/BUILD": f"python_sources(interpreter_constraints=['=={interpreter_constraints}'])",
        }
    )

    target = rule_runner.get_target(Address("src", relative_file_path="app.py"))
    stdout = run_run_request(rule_runner, target)
    named_caches_dir = (
        rule_runner.options_bootstrapper.bootstrap_options.for_global_scope().named_caches_dir
    )
    prefix_dir, version = stdout.splitlines()
    assert prefix_dir.startswith(f"{named_caches_dir}/pyenv")
    assert expected_version_substring in version


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
