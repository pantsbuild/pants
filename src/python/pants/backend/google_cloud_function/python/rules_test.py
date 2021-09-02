# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from io import BytesIO
from textwrap import dedent
from zipfile import ZipFile

import pytest

from pants.backend.google_cloud_function.python.rules import PythonGoogleCloudFunctionFieldSet
from pants.backend.google_cloud_function.python.rules import (
    rules as python_google_cloud_function_rules,
)
from pants.backend.google_cloud_function.python.target_types import PythonGoogleCloudFunction
from pants.backend.google_cloud_function.python.target_types import rules as target_rules
from pants.backend.python.subsystems.lambdex import Lambdex
from pants.backend.python.subsystems.lambdex import (
    rules as python_google_cloud_function_subsystem_rules,
)
from pants.backend.python.target_types import PythonLibrary
from pants.core.goals.package import BuiltPackage
from pants.core.target_types import Files, RelocatedFiles, Resources
from pants.core.target_types import rules as core_target_types_rules
from pants.engine.addresses import Address
from pants.engine.fs import DigestContents
from pants.testutil.python_interpreter_selection import all_major_minor_python_versions
from pants.testutil.rule_runner import QueryRule, RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *python_google_cloud_function_rules(),
            *python_google_cloud_function_subsystem_rules(),
            *target_rules(),
            *core_target_types_rules(),
            QueryRule(BuiltPackage, (PythonGoogleCloudFunctionFieldSet,)),
        ],
        target_types=[PythonGoogleCloudFunction, PythonLibrary, Files, RelocatedFiles, Resources],
    )


def create_python_google_cloud_function(
    rule_runner: RuleRunner, addr: Address, *, extra_args: list[str] | None = None
) -> tuple[str, bytes]:
    rule_runner.set_options(
        [
            "--backend-packages=pants.backend.google_cloud_function.python",
            "--source-root-patterns=src/python",
            *(extra_args or ()),
        ],
        env_inherit={"PATH", "PYENV_ROOT", "HOME"},
    )
    target = rule_runner.get_target(addr)
    built_asset = rule_runner.request(
        BuiltPackage, [PythonGoogleCloudFunctionFieldSet.create(target)]
    )
    assert (
        "    Runtime: python37",
        "    Handler: main.handler",
    ) == built_asset.artifacts[0].extra_log_lines
    digest_contents = rule_runner.request(DigestContents, [built_asset.digest])
    assert len(digest_contents) == 1
    relpath = built_asset.artifacts[0].relpath
    assert relpath is not None
    return relpath, digest_contents[0].content


@pytest.mark.platform_specific_behavior
@pytest.mark.parametrize(
    "major_minor_interpreter",
    all_major_minor_python_versions(Lambdex.default_interpreter_constraints),
)
def test_create_hello_world_lambda(rule_runner: RuleRunner, major_minor_interpreter: str) -> None:
    rule_runner.write_files(
        {
            "src/python/foo/bar/hello_world.py": dedent(
                """
                def handler(event, context):
                    print('Hello, World!')
                """
            ),
            "src/python/foo/bar/BUILD": dedent(
                """
                python_library(name='lib')

                python_google_cloud_function(
                    name='lambda',
                    dependencies=[':lib'],
                    handler='foo.bar.hello_world:handler',
                    runtime='python37',
                    type='event',
                )
                """
            ),
        }
    )
    zip_file_relpath, content = create_python_google_cloud_function(
        rule_runner,
        Address("src/python/foo/bar", target_name="lambda"),
        extra_args=[f"--lambdex-interpreter-constraints=['=={major_minor_interpreter}.*']"],
    )
    assert "src.python.foo.bar/lambda.zip" == zip_file_relpath
    zipfile = ZipFile(BytesIO(content))
    names = set(zipfile.namelist())
    assert "main.py" in names
    assert "foo/bar/hello_world.py" in names


def test_warn_files_targets(rule_runner: RuleRunner, caplog) -> None:
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
            "src/py/project/app.py": dedent(
                """\
                def handler(event, context):
                    print('Hello, World!')
                """
            ),
            "src/py/project/BUILD": dedent(
                """\
                python_library(
                    name='lib',
                    dependencies=['assets:files', 'assets:relocated', 'assets:resources'],
                )

                python_google_cloud_function(
                    name='lambda',
                    dependencies=[':lib'],
                    handler='foo.bar.hello_world:handler',
                    runtime='python37',
                    type='event',
                )
                """
            ),
        }
    )

    assert not caplog.records
    zip_file_relpath, _ = create_python_google_cloud_function(
        rule_runner, Address("src/py/project", target_name="lambda")
    )
    assert caplog.records
    assert "src.py.project/lambda.zip" == zip_file_relpath
    assert (
        "The python_google_cloud_function target src/py/project:lambda transitively depends on" in caplog.text
    )
    assert "assets/f.txt:files" in caplog.text
    assert "assets:relocated" in caplog.text
    assert "assets:resources" not in caplog.text
