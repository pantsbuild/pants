# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import json
import os
from textwrap import dedent
from typing import Tuple

import pytest

from pants.backend.codegen.protobuf.python import additional_fields as protobuf_additional_fields
from pants.backend.codegen.protobuf.python.python_protobuf_module_mapper import (
    rules as protobuf_module_mapper_rules,
)
from pants.backend.codegen.protobuf.python.python_protobuf_subsystem import (
    rules as protobuf_subsystem_rules,
)
from pants.backend.codegen.protobuf.python.rules import rules as protobuf_python_rules
from pants.backend.codegen.protobuf.target_types import ProtobufSourcesGeneratorTarget
from pants.backend.codegen.protobuf.target_types import rules as protobuf_target_types_rules
from pants.backend.python import target_types_rules
from pants.backend.python.dependency_inference import rules as dependency_inference_rules
from pants.backend.python.goals import package_dists
from pants.backend.python.goals.run_python_source import PythonSourceFieldSet
from pants.backend.python.goals.run_python_source import rules as run_rules
from pants.backend.python.macros.python_artifact import PythonArtifact
from pants.backend.python.target_types import (
    PythonDistribution,
    PythonRequirementTarget,
    PythonSourcesGeneratorTarget,
)
from pants.backend.python.util_rules import local_dists, pex_from_targets
from pants.build_graph.address import Address
from pants.core.goals.run import RunDebugAdapterRequest, RunRequest
from pants.engine.process import InteractiveProcess
from pants.engine.rules import QueryRule
from pants.engine.target import Target
from pants.testutil.debug_adapter_util import debugadapter_port_for_testing
from pants.testutil.pants_integration_test import run_pants
from pants.testutil.python_rule_runner import PythonRuleRunner
from pants.testutil.rule_runner import mock_console


@pytest.fixture
def rule_runner() -> PythonRuleRunner:
    return PythonRuleRunner(
        rules=[
            *run_rules(),
            *dependency_inference_rules.rules(),
            *target_types_rules.rules(),
            *local_dists.rules(),
            *pex_from_targets.rules(),
            *package_dists.rules(),
            *protobuf_subsystem_rules(),
            *protobuf_target_types_rules(),
            *protobuf_python_rules(),
            *protobuf_additional_fields.rules(),
            *protobuf_module_mapper_rules(),
            QueryRule(RunRequest, (PythonSourceFieldSet,)),
            QueryRule(RunDebugAdapterRequest, (PythonSourceFieldSet,)),
        ],
        target_types=[
            ProtobufSourcesGeneratorTarget,
            PythonSourcesGeneratorTarget,
            PythonRequirementTarget,
            PythonDistribution,
        ],
        objects={"python_artifact": PythonArtifact},
    )


def run_run_request(
    rule_runner: PythonRuleRunner,
    target: Target,
    test_debug_adapter: bool = True,
) -> Tuple[int, str, str]:
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
        result = rule_runner.run_interactive_process(run_process)
        stdout = mocked_console[1].get_stdout()
        stderr = mocked_console[1].get_stderr()

    if test_debug_adapter:
        debug_adapter_request = rule_runner.request(
            RunDebugAdapterRequest, [PythonSourceFieldSet.create(target)]
        )
        debug_adapter_process = InteractiveProcess(
            argv=debug_adapter_request.args,
            env=debug_adapter_request.extra_env,
            input_digest=debug_adapter_request.digest,
            run_in_workspace=True,
            immutable_input_digests=debug_adapter_request.immutable_input_digests,
            append_only_caches=debug_adapter_request.append_only_caches,
        )
        with mock_console(rule_runner.options_bootstrapper) as mocked_console:
            debug_adapter_result = rule_runner.run_interactive_process(debug_adapter_process)
            assert debug_adapter_result.exit_code == result.exit_code, mocked_console[
                1
            ].get_stderr()

    return result.exit_code, stdout, stderr


@pytest.mark.parametrize(
    "global_default_value, field_value, run_uses_sandbox",
    [
        # Nothing set -> True
        (None, None, True),
        # Field set -> use field value
        (None, True, True),
        (None, False, False),
        # Global default set -> use default
        (True, None, True),
        (False, None, False),
        # Both set -> use field
        (True, True, True),
        (True, False, False),
        (False, True, True),
        (False, False, False),
    ],
)
def test_run_sample_script(
    global_default_value: bool | None,
    field_value: bool | None,
    run_uses_sandbox: bool,
    rule_runner: PythonRuleRunner,
) -> None:
    """Test that we properly run a `python_source` target.

    This checks a few things:
    - We can handle source roots.
    - We run in-repo when requested, and handle codegen correctly.
    - We propagate the error code.
    """
    sources = {
        "src_root1/project/app.py": dedent(
            """\
            import sys
            from utils.strutil import my_file
            from codegen.hello_pb2 import Hi

            def main():
                print("Hola, mundo.", file=sys.stderr)
                print(my_file())
                sys.exit(23)

            if __name__ == "__main__":
              main()
            """
        ),
        "src_root1/project/BUILD": dedent(
            f"""\
            python_sources(
                {("run_goal_use_sandbox=" + str(field_value)) if field_value is not None else ""}
            )
            """
        ),
        "src_root2/utils/strutil.py": dedent(
            """\
            import os.path

            def my_file():
                return os.path.abspath(__file__)
            """
        ),
        "src_root2/utils/BUILD": "python_sources()",
        "src_root2/codegen/hello.proto": 'syntax = "proto3";\nmessage Hi {string name = 1;}',
        "src_root2/codegen/BUILD": dedent(
            """\
            protobuf_sources()
            python_requirement(name='protobuf', requirements=['protobuf'])
            """
        ),
    }

    rule_runner.write_files(sources)
    args = [
        "--backend-packages=pants.backend.python",
        "--backend-packages=pants.backend.codegen.protobuf.python",
        "--source-root-patterns=['src_root1', 'src_root2']",
        f"--debug-adapter-port={debugadapter_port_for_testing()}",
        *(
            (
                (
                    "--python-default-run-goal-use-sandbox"
                    if global_default_value
                    else "--no-python-default-run-goal-use-sandbox"
                ),
            )
            if global_default_value is not None
            else ()
        ),
    ]
    rule_runner.set_options(args, env_inherit={"PATH", "PYENV_ROOT", "HOME"})
    target = rule_runner.get_target(Address("src_root1/project", relative_file_path="app.py"))
    exit_code, stdout, stderr = run_run_request(rule_runner, target)

    assert "Hola, mundo.\n" in stderr
    file = stdout.strip()
    if run_uses_sandbox:
        assert file.endswith("src_root2/utils/strutil.py")
        assert "pants-sandbox-" in file
    else:
        assert file == os.path.join(rule_runner.build_root, "src_root2/utils/strutil.py")
    assert exit_code == 23


def test_no_strip_pex_env_issues_12057(rule_runner: PythonRuleRunner) -> None:
    sources = {
        "src/app.py": dedent(
            """\
            import os
            import sys


            if __name__ == "__main__":
                exit_code = os.environ.get("PANTS_ISSUES_12057")
                if exit_code is None:
                    os.environ["PANTS_ISSUES_12057"] = "42"
                    os.execv(sys.executable, [sys.executable, *sys.argv])
                sys.exit(int(exit_code))
            """
        ),
        "src/BUILD": dedent(
            """\
            python_sources()
            """
        ),
    }
    rule_runner.write_files(sources)
    args = [
        "--backend-packages=pants.backend.python",
        "--source-root-patterns=['src']",
    ]
    rule_runner.set_options(args, env_inherit={"PATH", "PYENV_ROOT", "HOME"})
    target = rule_runner.get_target(Address("src", relative_file_path="app.py"))
    exit_code, _, stderr = run_run_request(rule_runner, target, test_debug_adapter=False)
    assert exit_code == 42, stderr


@pytest.mark.parametrize("run_in_sandbox", [False, True])
def test_pex_root_location(rule_runner: PythonRuleRunner, run_in_sandbox: bool) -> None:
    # See issues #12055 and #17750.
    read_config_result = run_pants(["help-all"])
    read_config_result.assert_success()
    config_data = json.loads(read_config_result.stdout)
    global_advanced_options = {
        option["config_key"]: [
            ranked_value["value"] for ranked_value in option["value_history"]["ranked_values"]
        ][-1]
        for option in config_data["scope_to_help_info"][""]["advanced"]
    }
    named_caches_dir = global_advanced_options["named_caches_dir"]

    sources = {
        "src/app.py": "import os; print(__file__ + '\\n' + os.environ['PEX_ROOT'])",
        "src/BUILD": dedent(
            f"""\
            python_sources(run_goal_use_sandbox={run_in_sandbox})
            """
        ),
    }
    rule_runner.write_files(sources)
    args = [
        "--backend-packages=pants.backend.python",
        "--source-root-patterns=['src']",
    ]
    rule_runner.set_options(args, env_inherit={"PATH", "PYENV_ROOT", "HOME"})
    target = rule_runner.get_target(Address("src", relative_file_path="app.py"))
    exit_code, stdout, _ = run_run_request(rule_runner, target, test_debug_adapter=False)
    assert exit_code == 0
    app_file, pex_root = stdout.splitlines(keepends=False)
    sandbox = os.path.dirname(os.path.dirname(app_file))
    expected_pex_root = (
        os.path.join(sandbox, ".", ".cache", "pex_root")
        if run_in_sandbox
        else os.path.join(named_caches_dir, "pex_root")
    )
    assert expected_pex_root == pex_root


def test_local_dist(rule_runner: PythonRuleRunner) -> None:
    sources = {
        "foo/bar.py": "BAR = 'LOCAL DIST'",
        "foo/setup.py": dedent(
            """\
            from setuptools import setup

            setup(name="foo", version="9.8.7", packages=["foo"], package_dir={"foo": "."},)
            """
        ),
        "foo/main.py": "from foo.bar import BAR; print(BAR)",
        "foo/BUILD": dedent(
            """\
            python_sources(name="lib", sources=["bar.py", "setup.py"])

            python_distribution(
                name="dist",
                dependencies=[":lib"],
                provides=python_artifact(name="foo", version="9.8.7"),
                sdist=False,
                generate_setup=False,
            )

            python_sources(
                sources=["main.py"],
                # Force-exclude any dep on bar.py, so the only way to consume it is via the dist.
                dependencies=[":dist", "!:lib"],
            )
            """
        ),
    }
    rule_runner.write_files(sources)
    args = [
        "--backend-packages=pants.backend.python",
        "--source-root-patterns=['/']",
    ]
    rule_runner.set_options(args, env_inherit={"PATH", "PYENV_ROOT", "HOME"})
    target = rule_runner.get_target(Address("foo", relative_file_path="main.py"))
    exit_code, stdout, stderr = run_run_request(rule_runner, target)
    assert exit_code == 0
    assert stdout == "LOCAL DIST\n", stderr


def test_runs_in_venv(rule_runner: PythonRuleRunner) -> None:
    # NB: We aren't just testing an implementation detail, users can and should expect their code to
    # be run just as if they ran their code in a virtualenv (as is common in the Python ecosystem).
    sources = {
        "src/app.py": dedent(
            """\
            import os
            import sys

            if __name__ == "__main__":
                sys.exit(0 if "VIRTUAL_ENV" in os.environ else 1)
            """
        ),
        "src/BUILD": dedent(
            """\
            python_sources()
            """
        ),
    }
    rule_runner.write_files(sources)
    args = [
        "--backend-packages=pants.backend.python",
        "--source-root-patterns=['src']",
    ]
    rule_runner.set_options(args, env_inherit={"PATH", "PYENV_ROOT", "HOME"})
    target = rule_runner.get_target(Address("src", relative_file_path="app.py"))
    exit_code, stdout, _ = run_run_request(rule_runner, target)
    assert exit_code == 0, stdout
