# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import textwrap
from io import BytesIO
from typing import Tuple
from zipfile import ZipFile

import pytest

from pants.backend.awslambda.common.awslambda_common_rules import (
    AWSLambdaPythonRuntime,
    AWSLambdaPythonRequest,
)
from pants.backend.awslambda.common.awslambda_common_rules import rules as awslambda_common_rules
from pants.backend.awslambda.python.awslambda_python_rules import rules as awslambda_python_rules
from pants.backend.awslambda.python.target_types import PythonAWSLambda
from pants.backend.python.goals.create_python_binary import (
    PythonBinaryFieldSet,
    PythonBinaryImplementation,
    PythonEntryPointWrapper,
)
from pants.backend.python.target_types import PythonBinary, PythonLibrary
from pants.core.goals.binary import BinaryFieldSet, CreatedBinary
from pants.engine.addresses import Address
from pants.engine.fs import DigestContents
from pants.engine.rules import rule
from pants.testutil.rule_runner import QueryRule, RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *awslambda_common_rules(),
            *awslambda_python_rules(),
            QueryRule(CreatedBinary, (PythonBinaryFieldSet,)),
        ],
        target_types=[PythonBinary, PythonLibrary],
    )


def create_python_awslambda(
    rule_runner: RuleRunner,
    addr: str,
    *,
    runtime: AWSLambdaPythonRuntime,
) -> Tuple[str, bytes]:
    rule_runner.set_options(
        [
            "--backend-packages=pants.backend.awslambda.python",
            "--source-root-patterns=src/python",
            "--pants-distdir-legacy-paths=false",
            f"--awslambda-python-runtime={runtime}",
        ]
    )
    target = rule_runner.get_target(Address.parse(addr))
    created_awslambda = rule_runner.request(
        CreatedBinary, [PythonBinaryFieldSet.create(target)]
    )
    created_awslambda_digest_contents = rule_runner.request(
        DigestContents, [created_awslambda.digest]
    )
    assert len(created_awslambda_digest_contents) == 1
    return created_awslambda.binary_name, created_awslambda_digest_contents[0].content


def test_create_hello_world_lambda(rule_runner: RuleRunner) -> None:
    rule_runner.create_file(
        "src/python/foo/bar/hello_world.py",
        textwrap.dedent(
            """
            def handler(event, context):
                print('Hello, World!')
            """
        ),
    )

    rule_runner.add_to_build_file(
        "src/python/foo/bar",
        textwrap.dedent(
            """
            python_library(
              name='hello_world',
              sources=['hello_world.py']
            )

            python_binary(
              name='hello_world_lambda',
              dependencies=[':hello_world'],
              entry_point='foo.bar.hello_world',
            )
            """
        ),
    )

    zip_file_relpath, content = create_python_awslambda(
        rule_runner, "src/python/foo/bar:hello_world_lambda",
        runtime=AWSLambdaPythonRuntime.python37,
    )
    assert "src.python.foo.bar/hello_world_lambda.zip" == zip_file_relpath
    zipfile = ZipFile(BytesIO(content))
    names = set(zipfile.namelist())
    assert "lambdex_handler.py" in names
    assert "foo/bar/hello_world.py" in names
