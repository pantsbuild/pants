# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from io import BytesIO
from textwrap import dedent
from typing import Tuple
from zipfile import ZipFile

import pytest

from pants.backend.awslambda.python.rules import PythonAwsLambdaFieldSet
from pants.backend.awslambda.python.rules import rules as awslambda_python_rules
from pants.backend.awslambda.python.target_types import PythonAWSLambda
from pants.backend.awslambda.python.target_types import rules as target_rules
from pants.backend.python.target_types import PythonLibrary
from pants.core.goals.package import BuiltPackage
from pants.core.target_types import Files, RelocatedFiles, Resources
from pants.core.target_types import rules as core_target_types_rules
from pants.engine.addresses import Address
from pants.engine.fs import DigestContents
from pants.testutil.rule_runner import QueryRule, RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *awslambda_python_rules(),
            *target_rules(),
            *core_target_types_rules(),
            QueryRule(BuiltPackage, (PythonAwsLambdaFieldSet,)),
        ],
        target_types=[PythonAWSLambda, PythonLibrary, Files, RelocatedFiles, Resources],
    )


def create_python_awslambda(rule_runner: RuleRunner, addr: Address) -> Tuple[str, bytes]:
    rule_runner.set_options(
        [
            "--backend-packages=pants.backend.awslambda.python",
            "--source-root-patterns=src/python",
        ],
        env_inherit={"PATH", "PYENV_ROOT", "HOME"},
    )
    target = rule_runner.get_target(addr)
    built_asset = rule_runner.request(BuiltPackage, [PythonAwsLambdaFieldSet.create(target)])
    assert (
        "    Runtime: python3.7",
        "    Handler: lambdex_handler.handler",
    ) == built_asset.artifacts[0].extra_log_lines
    digest_contents = rule_runner.request(DigestContents, [built_asset.digest])
    assert len(digest_contents) == 1
    relpath = built_asset.artifacts[0].relpath
    assert relpath is not None
    return relpath, digest_contents[0].content


def test_create_hello_world_lambda(rule_runner: RuleRunner) -> None:
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

                python_awslambda(
                    name='lambda',
                    dependencies=[':lib'],
                    handler='foo.bar.hello_world:handler',
                    runtime='python3.7',
                )
                """
            ),
        }
    )
    zip_file_relpath, content = create_python_awslambda(
        rule_runner, Address("src/python/foo/bar", target_name="lambda")
    )
    assert "src.python.foo.bar/lambda.zip" == zip_file_relpath
    zipfile = ZipFile(BytesIO(content))
    names = set(zipfile.namelist())
    assert "lambdex_handler.py" in names
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

                python_awslambda(
                    name='lambda',
                    dependencies=[':lib'],
                    handler='foo.bar.hello_world:handler',
                    runtime='python3.7',
                )
                """
            ),
        }
    )

    assert not caplog.records
    zip_file_relpath, _ = create_python_awslambda(
        rule_runner, Address("src/py/project", target_name="lambda")
    )
    assert caplog.records
    assert "src.py.project/lambda.zip" == zip_file_relpath
    assert (
        "The python_awslambda target src/py/project:lambda transitively depends on" in caplog.text
    )
    assert "assets/f.txt:files" in caplog.text
    assert "assets:relocated" in caplog.text
    assert "assets:resources" not in caplog.text
