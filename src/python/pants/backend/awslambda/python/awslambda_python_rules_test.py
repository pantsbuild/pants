# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import textwrap
from io import BytesIO
from typing import Tuple
from zipfile import ZipFile

from pants.backend.awslambda.common.awslambda_common_rules import CreatedAWSLambda
from pants.backend.awslambda.python.awslambda_python_rules import rules as awslambda_python_rules
from pants.build_graph.address import Address
from pants.engine.fs import FilesContent
from pants.engine.legacy.graph import HydratedTarget
from pants.engine.legacy.structs import PythonAWSLambdaAdaptor
from pants.engine.rules import RootRule
from pants.engine.selectors import Params
from pants.testutil.option.util import create_options_bootstrapper
from pants.testutil.test_base import TestBase


class TestPythonAWSLambdaCreation(TestBase):

  @classmethod
  def rules(cls):
    return (*super().rules(), *awslambda_python_rules(), RootRule(PythonAWSLambdaAdaptor))

  def create_python_awslambda(self, addr: str) -> Tuple[str, bytes]:
    target = self.request_single_product(HydratedTarget, Address.parse(addr))
    created_awslambda = self.request_single_product(
      CreatedAWSLambda,
      Params(
        target.adaptor,
        create_options_bootstrapper(args=["--backend-packages2=pants.backend.awslambda.python"]),
      ),
    )
    files_content = list(self.request_single_product(FilesContent,
                                                     Params(created_awslambda.digest)))
    assert len(files_content) == 1
    return created_awslambda.name, files_content[0].content

  def test_create_hello_world_lambda(self) -> None:
    self.create_file('src/python/foo/bar/hello_world.py', textwrap.dedent("""
      def handler(event, context):
        print('Hello, World!')
    """))

    self.create_file('src/python/foo/bar/BUILD', textwrap.dedent("""
      python_library(
        name='hello_world',
        sources=['hello_world.py']
      )

      python_awslambda(
        name='hello_world_lambda',
        dependencies=[':hello_world'],
        handler='foo.bar.hello_world'
      )
    """))

    name, content = self.create_python_awslambda('src/python/foo/bar:hello_world_lambda')
    assert 'hello_world_lambda.pex' == name
    zipfile = ZipFile(BytesIO(content))
    names = set(zipfile.namelist())
    assert 'lambdex_handler.py' in names
    assert 'foo/bar/hello_world.py' in names
