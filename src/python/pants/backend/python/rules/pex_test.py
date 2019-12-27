# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import json
import os.path
import zipfile
from typing import Dict, Optional, cast

from pants.backend.python.rules.download_pex_bin import download_pex_bin
from pants.backend.python.rules.pex import (
  CreatePex,
  Pex,
  PexInterpreterConstraints,
  PexRequirements,
  create_pex,
)
from pants.backend.python.subsystems.python_native_code import (
  PythonNativeCode,
  create_pex_native_build_environment,
)
from pants.backend.python.subsystems.python_setup import PythonSetup
from pants.backend.python.subsystems.subprocess_environment import (
  SubprocessEnvironment,
  create_subprocess_encoding_environment,
)
from pants.engine.fs import Digest, DirectoryToMaterialize, FileContent, InputFilesContent
from pants.engine.isolated_process import ExecuteProcessRequest, ExecuteProcessResult
from pants.engine.rules import RootRule
from pants.engine.selectors import Params
from pants.testutil.subsystem.util import init_subsystems
from pants.testutil.test_base import TestBase
from pants.util.strutil import create_path_env_var


class TestResolveRequirements(TestBase):

  @classmethod
  def rules(cls):
    return super().rules() + [
      create_pex,
      create_pex_native_build_environment,
      create_subprocess_encoding_environment,
      download_pex_bin,
      RootRule(CreatePex),
      RootRule(PythonSetup),
      RootRule(PythonNativeCode),
      RootRule(SubprocessEnvironment)
    ]

  def setUp(self):
    super().setUp()
    init_subsystems([PythonSetup, PythonNativeCode, SubprocessEnvironment])

  def create_pex_and_get_all_data(self, *, requirements=PexRequirements(),
      entry_point=None,
      interpreter_constraints=PexInterpreterConstraints(),
      input_files: Optional[Digest] = None) -> Dict:
    request = CreatePex(
      output_filename="test.pex",
      requirements=requirements,
      interpreter_constraints=interpreter_constraints,
      entry_point=entry_point,
      input_files_digest=input_files,
    )
    requirements_pex = self.request_single_product(
      Pex,
      Params(
        request,
        PythonSetup.global_instance(),
        SubprocessEnvironment.global_instance(),
        PythonNativeCode.global_instance()
      )
    )
    self.scheduler.materialize_directory(
      DirectoryToMaterialize(requirements_pex.directory_digest),
    )
    with zipfile.ZipFile(os.path.join(self.build_root, "test.pex"), "r") as pex:
      with pex.open("PEX-INFO", "r") as pex_info:
        pex_info_content = pex_info.readline().decode()
        pex_list = pex.namelist()
    return {'pex': requirements_pex, 'info': json.loads(pex_info_content), 'files': pex_list}

  def create_pex_and_get_pex_info(
    self, *, requirements=PexRequirements(), entry_point=None,
    interpreter_constraints=PexInterpreterConstraints(),
    input_files: Optional[Digest] = None) -> Dict:
    return cast(Dict, self.create_pex_and_get_all_data(
      requirements=requirements,
      entry_point=entry_point,
      interpreter_constraints=interpreter_constraints,
      input_files=input_files
    )['info'])

  def test_generic_pex_creation(self) -> None:
    input_files_content = InputFilesContent((
      FileContent(path='main.py', content=b'print("from main")'),
      FileContent(path='subdir/sub.py', content=b'print("from sub")'),
    ))

    input_files = self.request_single_product(Digest, input_files_content)
    pex_output = self.create_pex_and_get_all_data(entry_point='main', input_files=input_files)

    pex_files = pex_output['files']
    self.assertTrue('pex' not in pex_files)
    self.assertTrue('main.py' in pex_files)
    self.assertTrue('subdir/sub.py' in pex_files)

    python_setup = PythonSetup.global_instance()
    env = {"PATH": create_path_env_var(python_setup.interpreter_search_paths)}

    pex = pex_output['pex']

    req = ExecuteProcessRequest(argv=('python', 'test.pex'), env=env, input_files=pex.directory_digest, description="Run the pex and make sure it works")
    result = self.request_single_product(ExecuteProcessResult, req)
    self.assertEqual(result.stdout, b"from main\n")

  def test_resolves_dependencies(self) -> None:
    requirements = PexRequirements(requirements=("six==1.12.0", "jsonschema==2.6.0", "requests==2.22.0"))
    pex_info = self.create_pex_and_get_pex_info(requirements=requirements)
    # NB: We do not check for transitive dependencies, which PEX-INFO will include. We only check
    # that at least the dependencies we requested are included.
    self.assertTrue(set(requirements.requirements).issubset(pex_info["requirements"]))

  def test_entry_point(self) -> None:
    entry_point = "pydoc"
    pex_info = self.create_pex_and_get_pex_info(entry_point=entry_point)
    self.assertEqual(pex_info["entry_point"], entry_point)

  def test_interpreter_constraints(self) -> None:
    constraints = PexInterpreterConstraints(
        constraint_set=("CPython>=2.7,<3", "CPython>=3.6")
    )
    pex_info = self.create_pex_and_get_pex_info(interpreter_constraints=constraints)
    self.assertEqual(set(pex_info["interpreter_constraints"]), set(constraints.constraint_set))
