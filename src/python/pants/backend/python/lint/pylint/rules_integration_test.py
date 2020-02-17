# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from functools import partialmethod
from textwrap import dedent
from typing import List, Optional

import pytest

from pants.backend.python.lint.pylint.rules import PylintTarget
from pants.backend.python.lint.pylint.rules import rules as pylint_rules
from pants.backend.python.targets.python_library import PythonLibrary
from pants.base.specs import OriginSpec, SingleAddress
from pants.build_graph.address import Address
from pants.build_graph.build_file_aliases import BuildFileAliases
from pants.engine.fs import FileContent, InputFilesContent, Snapshot
from pants.engine.legacy.structs import PythonTargetAdaptor, PythonTargetAdaptorWithOrigin
from pants.engine.rules import RootRule
from pants.engine.selectors import Params
from pants.rules.core.lint import LintResult
from pants.source.wrapped_globs import EagerFilesetWithSpec
from pants.testutil.option.util import create_options_bootstrapper
from pants.testutil.test_base import TestBase


class PylintIntegrationTest(TestBase):
  # See http://pylint.pycqa.org/en/latest/user_guide/run.html#exit-codes for exit codes.
  source_root = "src/python"
  good_source = FileContent(
    path=f"{source_root}/good.py", content=b"'''docstring'''\nUPPERCASE_CONSTANT = ''\n",
  )
  bad_source = FileContent(
    path=f"{source_root}/bad.py", content=b"'''docstring'''\nlowercase_constant = ''\n",
  )

  create_python_library = partialmethod(
    TestBase.create_library, path=source_root, target_type="python_library", name="target",
  )

  def write_file(self, file_content: FileContent) -> None:
    self.create_file(
      relpath=file_content.path, contents=file_content.content.decode()
    )

  @classmethod
  def alias_groups(cls) -> BuildFileAliases:
    return BuildFileAliases(targets={'python_library': PythonLibrary})

  @classmethod
  def rules(cls):
    return (*super().rules(), *pylint_rules(), RootRule(PylintTarget))

  def run_pylint(
    self,
    source_files: List[FileContent],
    *,
    config: Optional[str] = None,
    passthrough_args: Optional[str] = None,
    interpreter_constraints: Optional[str] = None,
    skip: bool = False,
    origin: Optional[OriginSpec] = None,
  ) -> LintResult:
    args = ["--backend-packages2=pants.backend.python.lint.pylint"]
    if config:
      # TODO: figure out how to get this file to exist...
      self.create_file(relpath="pylintrc", contents=config)
      args.append("--pylint-config=pylintrc")
    if passthrough_args:
      args.append(f"--pylint-args='{passthrough_args}'")
    if skip:
      args.append(f"--pylint-skip")
    input_snapshot = self.request_single_product(Snapshot, InputFilesContent(source_files))
    adaptor = PythonTargetAdaptor(
      sources=EagerFilesetWithSpec(self.source_root, {'globs': []}, snapshot=input_snapshot),
      address=Address.parse(f"{self.source_root}:target"),
      compatibility=[interpreter_constraints] if interpreter_constraints else None,
    )
    if origin is None:
      origin = SingleAddress(directory="test", name="target")
    target = PylintTarget(PythonTargetAdaptorWithOrigin(adaptor, origin))
    return self.request_single_product(
      LintResult, Params(target, create_options_bootstrapper(args=args)),
    )

  def test_single_passing_source(self) -> None:
    self.create_python_library()
    self.write_file(self.good_source)
    result = self.run_pylint([self.good_source])
    assert result.exit_code == 0
    assert "Your code has been rated at 10.00/10" in result.stdout.strip()

  def test_single_failing_source(self) -> None:
    self.create_python_library()
    self.write_file(self.bad_source)
    result = self.run_pylint([self.bad_source])
    assert result.exit_code == 16  # convention message issued
    assert "bad.py:2:0: C0103" in result.stdout

  def test_mixed_sources(self) -> None:
    self.create_python_library()
    self.write_file(self.good_source)
    self.write_file(self.bad_source)
    result = self.run_pylint([self.good_source, self.bad_source])
    assert result.exit_code == 16  # convention message issued
    assert "good.py" not in result.stdout
    assert "bad.py:2:0: C0103" in result.stdout

  def test_precise_file_args(self) -> None:
    self.create_python_library()
    self.write_file(self.good_source)
    self.write_file(self.bad_source)
    result = self.run_pylint([self.good_source])
    assert result.exit_code == 0
    assert "Your code has been rated at 10.00/10" in result.stdout.strip()

  @pytest.mark.skip(reason="Get config file creation to work with options parsing")
  def test_respects_config_file(self) -> None:
    self.create_python_library()
    self.write_file(self.bad_source)
    result = self.run_pylint([self.bad_source], config="[pylint]\ndisable = C0103\n")
    assert result.exit_code == 0
    assert result.stdout.strip() == ""

  def test_respects_passthrough_args(self) -> None:
    self.create_python_library()
    self.write_file(self.bad_source)
    result = self.run_pylint([self.bad_source], passthrough_args="--disable=C0103")
    assert result.exit_code == 0
    assert "Your code has been rated at 10.00/10" in result.stdout.strip()

  def test_includes_direct_dependencies(self) -> None:
    self.create_python_library(name="library")
    self.create_python_library(
      name="dependency", sources=["dependency.py"], dependencies=[":library"],
    )
    self.write_file(
      FileContent(
        path=f"{self.source_root}/dependency.py",
        content=dedent(
          """\
          # No docstring because Pylint doesn't lint dependencies
          from transitive_dep import doesnt_matter_if_variable_exists
          THIS_VARIABLE_EXISTS = ''
          """
        ).encode(),
      )
    )
    source = FileContent(
      path=f"{self.source_root}/test_dependency.py",
      content=dedent(
        """\
        '''Code is not executed, but Pylint will check that variables exist and are used'''
        from dependency import THIS_VARIABLE_EXISTS
        print(THIS_VARIABLE_EXISTS)
        """
      ).encode(),
    )
    self.create_python_library(sources=["test_dependency.py"], dependencies=[":dependency"])
    self.write_file(source)
    result = self.run_pylint([source])
    assert result.exit_code == 0
    assert "Your code has been rated at 10.00/10" in result.stdout.strip()

  def test_skip(self) -> None:
    result = self.run_pylint([self.bad_source], skip=True)
    assert result == LintResult.noop()
