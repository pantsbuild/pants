# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import textwrap
from io import BytesIO
from typing import Tuple
from zipfile import ZipFile

import pytest

from pants.backend.awslambda.common.awslambda_common_rules import CreatedAWSLambda
from pants.backend.awslambda.python.awslambda_python_rules import (
    PythonAwsLambdaConfiguration,
    get_interpreter_from_runtime,
)
from pants.backend.awslambda.python.awslambda_python_rules import rules as awslambda_python_rules
from pants.backend.awslambda.python.targets import PythonAWSLambda
from pants.backend.python.rules.targets import PythonLibrary
from pants.build_graph.address import Address
from pants.engine.fs import FilesContent
from pants.engine.rules import RootRule
from pants.engine.selectors import Params
from pants.engine.target import WrappedTarget
from pants.testutil.option.util import create_options_bootstrapper
from pants.testutil.test_base import TestBase


@pytest.mark.parametrize(
    ["runtime", "expected_major", "expected_minor"],
    (
        # The available runtimes at the time of writing.
        # See https://docs.aws.amazon.com/lambda/latest/dg/lambda-runtimes.html.
        ["python2.7", 2, 7],
        ["python3.6", 3, 6],
        ["python3.7", 3, 7],
        ["python3.8", 3, 8],
    ),
)
def test_get_interpreter_from_runtime(runtime, expected_major, expected_minor):
    assert (expected_major, expected_minor) == get_interpreter_from_runtime(runtime, "")


class TestPythonAWSLambdaCreation(TestBase):
    @classmethod
    def rules(cls):
        return (*super().rules(), *awslambda_python_rules(), RootRule(PythonAwsLambdaConfiguration))

    @classmethod
    def target_types(cls):
        return [PythonAWSLambda, PythonLibrary]

    def create_python_awslambda(self, addr: str) -> Tuple[str, bytes]:
        target = self.request_single_product(WrappedTarget, Address.parse(addr)).target
        created_awslambda = self.request_single_product(
            CreatedAWSLambda,
            Params(
                PythonAwsLambdaConfiguration.create(target),
                create_options_bootstrapper(
                    args=["--backend-packages2=pants.backend.awslambda.python"]
                ),
            ),
        )
        files_content = self.request_single_product(FilesContent, created_awslambda.digest)
        assert len(files_content) == 1
        return created_awslambda.name, files_content[0].content

    def test_create_hello_world_lambda(self) -> None:
        self.create_file(
            "src/python/foo/bar/hello_world.py",
            textwrap.dedent(
                """
                def handler(event, context):
                  print('Hello, World!')
                """
            ),
        )

        self.create_file(
            "src/python/foo/bar/BUILD",
            textwrap.dedent(
                """
                python_library(
                  name='hello_world',
                  sources=['hello_world.py']
                )

                python_awslambda(
                  name='hello_world_lambda',
                  dependencies=[':hello_world'],
                  handler='foo.bar.hello_world',
                  runtime='python3.7'
                )
                """
            ),
        )

        name, content = self.create_python_awslambda("src/python/foo/bar:hello_world_lambda")
        assert "hello_world_lambda.pex" == name
        zipfile = ZipFile(BytesIO(content))
        names = set(zipfile.namelist())
        assert "lambdex_handler.py" in names
        assert "foo/bar/hello_world.py" in names
