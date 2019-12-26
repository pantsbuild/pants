# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import textwrap
from io import BytesIO
from typing import Tuple
from zipfile import ZipFile

from pants.backend.awslambda.common.awslambda_common_rules import CreatedAWSLambda
from pants.backend.awslambda.python.awslambda_python_rules import (
  LambdexSetup,
  create_python_awslambda,
  setup_lambdex,
)
from pants.backend.awslambda.python.lambdex import Lambdex
from pants.backend.python.rules.download_pex_bin import download_pex_bin
from pants.backend.python.rules.inject_init import inject_init
from pants.backend.python.rules.pex import create_pex
from pants.backend.python.rules.pex_from_target_closure import create_pex_from_target_closure
from pants.backend.python.subsystems.python_native_code import (
  PythonNativeCode,
  create_pex_native_build_environment,
)
from pants.backend.python.subsystems.python_setup import PythonSetup
from pants.backend.python.subsystems.subprocess_environment import (
  SubprocessEnvironment,
  create_subprocess_encoding_environment,
)
from pants.build_graph.address import Address
from pants.engine.fs import Digest, FilesContent
from pants.engine.legacy.graph import HydratedTarget
from pants.engine.legacy.structs import PythonAWSLambdaAdaptor
from pants.engine.rules import RootRule
from pants.engine.selectors import Params
from pants.rules.core.strip_source_root import strip_source_root
from pants.source.source_root import SourceRootConfig
from pants.testutil.subsystem.util import init_subsystems
from pants.testutil.test_base import TestBase


class TestPythonAWSLambdaCreation(TestBase):

  @classmethod
  def rules(cls):
    # TODO: A convenient way to bring in all the rules needed to build a pex without
    # having to enumerate them here.
    return super().rules() + [
      create_python_awslambda,
      setup_lambdex,
      create_pex,
      create_pex_native_build_environment,
      create_subprocess_encoding_environment,
      strip_source_root,
      download_pex_bin,
      inject_init,
      create_pex_from_target_closure,
      RootRule(Digest),
      RootRule(SourceRootConfig),
      RootRule(PythonSetup),
      RootRule(PythonNativeCode),
      RootRule(SubprocessEnvironment),
      RootRule(Lambdex),
      RootRule(LambdexSetup),
      RootRule(PythonAWSLambdaAdaptor),
    ]

  def setUp(self):
    super().setUp()
    init_subsystems([SourceRootConfig, PythonSetup, PythonNativeCode,
                     SubprocessEnvironment, Lambdex])

  def create_python_awslambda(self, addr: str) -> Tuple[str, bytes]:
    lambdex_setup = self.request_single_product(
      LambdexSetup,
      Params(
        PythonSetup.global_instance(),
        PythonNativeCode.global_instance(),
        SubprocessEnvironment.global_instance(),
        Lambdex.global_instance(),
      )
    )
    target = self.request_single_product(HydratedTarget, Address.parse(addr))
    created_awslambda = self.request_single_product(
      CreatedAWSLambda,
      Params(
        target.adaptor,
        lambdex_setup,
        SourceRootConfig.global_instance(),
        PythonSetup.global_instance(),
        PythonNativeCode.global_instance(),
        SubprocessEnvironment.global_instance(),
      )
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
