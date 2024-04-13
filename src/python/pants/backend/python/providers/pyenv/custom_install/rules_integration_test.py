# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from textwrap import dedent

import pytest

from pants.backend.python import target_types_rules
from pants.backend.python.dependency_inference import rules as dependency_inference_rules
from pants.backend.python.goals.run_python_source import PythonSourceFieldSet
from pants.backend.python.goals.run_python_source import rules as run_rules
from pants.backend.python.providers.pyenv.custom_install.rules import RunPyenvInstallFieldSet
from pants.backend.python.providers.pyenv.custom_install.rules import (
    rules as pyenv_custom_install_rules,
)
from pants.backend.python.providers.pyenv.custom_install.target_types import PyenvInstall
from pants.backend.python.target_types import PythonSourcesGeneratorTarget
from pants.build_graph.address import Address
from pants.core.goals.run import RunRequest
from pants.engine.process import InteractiveProcess
from pants.engine.rules import QueryRule
from pants.engine.target import Target
from pants.testutil.rule_runner import RuleRunner, mock_console


@pytest.fixture
def named_caches_dir(tmp_path):
    return f"{tmp_path}/named_cache"


@pytest.fixture
def rule_runner(named_caches_dir) -> RuleRunner:
    return RuleRunner(
        rules=[
            *run_rules(),
            *pyenv_custom_install_rules(),
            *dependency_inference_rules.rules(),
            *target_types_rules.rules(),
            QueryRule(RunRequest, (PythonSourceFieldSet,)),
            QueryRule(RunRequest, (RunPyenvInstallFieldSet,)),
        ],
        target_types=[
            PythonSourcesGeneratorTarget,
            PyenvInstall,
        ],
        bootstrap_args=[
            f"--named-caches-dir={named_caches_dir}",
        ],
    )


def run_run_request(
    rule_runner: RuleRunner,
    target: Target,
) -> str:
    args = [
        (
            "--backend-packages=["
            + "'pants.backend.python',"
            + "'pants.backend.python.providers.experimental.pyenv',"
            + "'pants.backend.python.providers.experimental.pyenv.custom_install',"
            + "]"
        ),
        "--source-root-patterns=['src']",
    ]
    # Run the install
    install_target = rule_runner.get_target(
        Address(target_name="pants-pyenv-install", spec_path="")
    )
    rule_runner.set_options(args, env_inherit={"PATH", "PYENV_ROOT", "HOME"})
    run_request = rule_runner.request(RunRequest, [RunPyenvInstallFieldSet.create(install_target)])
    run_process = InteractiveProcess(
        argv=run_request.args + ("3.9.16",),
        env=run_request.extra_env,
        input_digest=run_request.digest,
        run_in_workspace=True,
        immutable_input_digests=run_request.immutable_input_digests,
        append_only_caches=run_request.append_only_caches,
    )
    with mock_console(rule_runner.options_bootstrapper) as mocked_console:
        rule_runner.run_interactive_process(run_process)
        print(mocked_console[1].get_stdout().strip())
        print(mocked_console[1].get_stderr().strip())
        assert "versions/3.9.16/bin/python" in mocked_console[1].get_stdout().strip()

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


def test_custom_install(rule_runner, named_caches_dir):
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
            "src/BUILD": "python_sources(interpreter_constraints=['==3.9.16'])",
        }
    )

    target = rule_runner.get_target(Address("src", relative_file_path="app.py"))
    stdout = run_run_request(rule_runner, target)
    prefix_dir, version = stdout.splitlines()
    assert prefix_dir.startswith(f"{named_caches_dir}/pyenv")
    assert "3.9.16" in version
