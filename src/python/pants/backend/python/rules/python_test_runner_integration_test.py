# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from functools import partialmethod
from pathlib import Path, PurePath
from textwrap import dedent
from typing import List, Optional

from pants.backend.python.python_requirement import PythonRequirement
from pants.backend.python.rules import (
  download_pex_bin,
  inject_init,
  prepare_chrooted_python_sources,
)
from pants.backend.python.rules.pex import create_pex
from pants.backend.python.rules.pex_from_target_closure import (
  CreatePexFromTargetClosure,
  create_pex_from_target_closure,
)
from pants.backend.python.rules.python_test_runner import (
  TestTargetSetup,
  debug_python_test,
  run_python_test,
  setup_pytest_for_target,
)
from pants.backend.python.subsystems.pytest import PyTest
from pants.backend.python.subsystems.python_native_code import (
  PythonNativeCode,
  create_pex_native_build_environment,
)
from pants.backend.python.subsystems.python_setup import PythonSetup
from pants.backend.python.subsystems.subprocess_environment import (
  SubprocessEnvironment,
  create_subprocess_encoding_environment,
)
from pants.backend.python.targets.python_library import PythonLibrary
from pants.backend.python.targets.python_requirement_library import PythonRequirementLibrary
from pants.backend.python.targets.python_tests import PythonTests
from pants.build_graph.address import BuildFileAddress
from pants.build_graph.build_file_aliases import BuildFileAliases
from pants.engine.fs import FileContent, create_fs_rules
from pants.engine.interactive_runner import InteractiveRunner
from pants.engine.legacy.structs import PythonTestsAdaptor
from pants.engine.rules import RootRule
from pants.engine.selectors import Params
from pants.option.global_options import GlobalOptions
from pants.option.option_value_container import OptionValueContainer
from pants.option.ranked_value import RankedValue
from pants.rules.core.strip_source_root import strip_source_root
from pants.rules.core.test import Status, TestDebugResult, TestOptions, TestResult
from pants.source.source_root import SourceRootConfig
from pants.testutil.interpreter_selection_utils import skip_unless_python27_and_python3_present
from pants.testutil.subsystem.util import global_subsystem_instance, init_subsystems
from pants.testutil.test_base import TestBase


class PythonTestRunnerIntegrationTest(TestBase):

  source_root = "tests/python/pants_test"
  good_source = FileContent(path="test_good.py", content=b"def test():\n  pass\n")
  bad_source = FileContent(path="test_bad.py", content=b"def test():\n  assert False\n")
  py3_only_source = FileContent(path="test_py3.py", content=b"def test() -> None:\n  pass\n")
  library_source = FileContent(path="library.py", content=b"def add_two(x):\n  return x + 2\n")

  create_python_library = partialmethod(
    TestBase.create_library, path=source_root, target_type="python_library",
  )

  def write_file(self, file_content: FileContent) -> None:
    self.create_file(
      relpath=str(PurePath(self.source_root, file_content.path)),
      contents=file_content.content.decode(),
    )

  def create_basic_library(self) -> None:
    self.create_python_library(name="library", sources=[self.library_source.path])
    self.write_file(self.library_source)

  def create_python_test_target(
    self,
    source_files: List[FileContent],
    *,
    dependencies: Optional[List[str]] = None,
    interpreter_constraints: Optional[str] = None,
  ) -> None:
    self.add_to_build_file(
      relpath=self.source_root,
      target=dedent(
        f"""\
        python_tests(
          name='target',
          dependencies={dependencies or []},
          compatibility={[interpreter_constraints] if interpreter_constraints else []},
        )
        """
      )
    )
    for source_file in source_files:
      self.write_file(source_file)

  def setup_thirdparty_dep(self) -> None:
    self.add_to_build_file(
      relpath="3rdparty/python",
      target=dedent(
        """\
        python_requirement_library(
          name='ordered-set',
          requirements=[python_requirement('ordered-set==3.1.1')],
        )
        """
      ),
    )

  @classmethod
  def alias_groups(cls) -> BuildFileAliases:
    return BuildFileAliases(
      targets={
        'python_library': PythonLibrary,
        'python_tests': PythonTests,
        "python_requirement_library": PythonRequirementLibrary,
      },
      objects={
        "python_requirement": PythonRequirement,
      }
    )

  @classmethod
  def rules(cls):
    return (
      *super().rules(),
      create_pex,
      create_pex_from_target_closure,
      create_pex_native_build_environment,
      create_subprocess_encoding_environment,
      debug_python_test,
      run_python_test,
      setup_pytest_for_target,
      strip_source_root,
      *create_fs_rules(),
      *download_pex_bin.rules(),
      *inject_init.rules(),
      *prepare_chrooted_python_sources.rules(),
      RootRule(CreatePexFromTargetClosure),
      RootRule(GlobalOptions),
      RootRule(PyTest),
      RootRule(PythonTestsAdaptor),
      RootRule(PythonSetup),
      RootRule(PythonNativeCode),
      RootRule(TestOptions),
      RootRule(TestTargetSetup),
      RootRule(SourceRootConfig),
      RootRule(SubprocessEnvironment),
    )

  def setUp(self):
    super().setUp()
    init_subsystems([
      PyTest, PythonSetup, PythonNativeCode, SourceRootConfig, SubprocessEnvironment,
    ])

  def run_pytest(self, *, passthrough_args: Optional[str] = None) -> TestResult:
    target = PythonTestsAdaptor(
      address=BuildFileAddress(rel_path=f"{self.source_root}/BUILD", target_name="target"),
    )
    pytest_subsystem = global_subsystem_instance(
      PyTest, options={
        PyTest.options_scope: {
          "args": [passthrough_args] if passthrough_args else [],
          "version": "pytest>=4.6.6,<4.7",  # so that we can run Python 2 tests
        },
      },
    )
    test_target_setup = self.request_single_product(
      TestTargetSetup,
      Params(
        target,
        pytest_subsystem,
        PythonNativeCode.global_instance(),
        PythonSetup.global_instance(),
        # TODO: How to pass an instance to `TestOptions`...? (A GoalSubsystem). Probably we should
        # just use OptionsBootstrapper.
        SourceRootConfig.global_instance(),
        SubprocessEnvironment.global_instance(),
      ),
    )
    # TODO: replace all this boilerplate with a utility to set up OptionsBootstrapper for
    # non-ConsoleRuleTestBase tests.
    mock_global_options = OptionValueContainer()
    mock_global_options.colors = RankedValue(RankedValue.HARDCODED, False)
    test_result = self.request_single_product(
      TestResult,
      Params(
        target,
        test_target_setup,
        PythonSetup.global_instance(),
        SubprocessEnvironment.global_instance(),
        GlobalOptions(mock_global_options),
      )
    )
    debug_result = self.request_single_product(
      TestDebugResult, Params(test_target_setup, InteractiveRunner(self.scheduler)),
    )
    if test_result.status == Status.SUCCESS:
      assert debug_result.exit_code == 0
    else:
      assert debug_result.exit_code != 0
    return test_result

  def test_single_passing_test(self) -> None:
    self.create_python_test_target([self.good_source])
    result = self.run_pytest()
    assert result.status == Status.SUCCESS
    assert "test_good.py ." in result.stdout

  def test_single_failing_test(self) -> None:
    self.create_python_test_target([self.bad_source])
    result = self.run_pytest()
    assert result.status == Status.FAILURE
    assert "test_bad.py F" in result.stdout

  def test_mixed_sources(self) -> None:
    self.create_python_test_target([self.good_source, self.bad_source])
    result = self.run_pytest()
    assert result.status == Status.FAILURE
    assert "test_good.py ." in result.stdout
    assert "test_bad.py F" in result.stdout

  def test_absolute_import(self) -> None:
    self.create_basic_library()
    source = FileContent(
      path="test_absolute_import.py",
      content=dedent(
        """\
        from pants_test.library import add_two

        def test():
          assert add_two(2) == 4
        """
      ).encode(),
    )
    self.create_python_test_target([source], dependencies=[":library"])
    result = self.run_pytest()
    assert result.status == Status.SUCCESS
    assert "test_absolute_import.py ." in result.stdout

  def test_relative_import(self) -> None:
    self.create_basic_library()
    source = FileContent(
      path="test_relative_import.py",
      content=dedent(
        """\
        from .library import add_two

        def test():
          assert add_two(2) == 4
        """
      ).encode(),
    )
    self.create_python_test_target([source], dependencies=[":library"])
    result = self.run_pytest()
    assert result.status == Status.SUCCESS
    assert "test_relative_import.py ." in result.stdout

  def test_transitive_dep(self) -> None:
    self.create_basic_library()
    self.create_python_library(
      name="transitive_dep", sources=["transitive_dep.py"], dependencies=[":library"],
    )
    self.write_file(
      FileContent(
        path="transitive_dep.py",
        content=dedent(
          """\
          from pants_test.library import add_two
  
          def add_four(x):
            return add_two(x) + 2
          """
        ).encode(),
      )
    )
    source = FileContent(
      path="test_transitive_dep.py",
      content=dedent(
        """\
        from pants_test.transitive_dep import add_four

        def test():
          assert add_four(2) == 6
        """
      ).encode(),
    )
    self.create_python_test_target([source], dependencies=[":transitive_dep"])
    result = self.run_pytest()
    assert result.status == Status.SUCCESS
    assert "test_transitive_dep.py ." in result.stdout

  def test_thirdparty_dep(self) -> None:
    self.setup_thirdparty_dep()
    source = FileContent(
      path="test_3rdparty_dep.py",
      content=dedent(
        """\
        from ordered_set import OrderedSet

        def test():
          assert OrderedSet((1, 2)) == OrderedSet([1, 2])
        """
      ).encode(),
    )
    self.create_python_test_target([source], dependencies=["3rdparty/python:ordered-set"])
    result = self.run_pytest()
    assert result.status == Status.SUCCESS
    assert "test_3rdparty_dep.py ." in result.stdout

  def test_thirdparty_transitive_dep(self) -> None:
    self.setup_thirdparty_dep()
    self.create_python_library(
      name="library", sources=["library.py"], dependencies=["3rdparty/python:ordered-set"],
    )
    self.write_file(
      FileContent(
        path="library.py",
        content=dedent(
          """\
          import string
          from ordered_set import OrderedSet
          
          alphabet = OrderedSet(string.ascii_lowercase)
          """
        ).encode(),
      )
    )
    source = FileContent(
      path="test_3rdparty_transitive_dep.py",
      content=dedent(
        """\
        from pants_test.library import alphabet

        def test():
          assert 'a' in alphabet and 'z' in alphabet
        """
      ).encode(),
    )
    self.create_python_test_target([source], dependencies=[":library"])
    result = self.run_pytest()
    assert result.status == Status.SUCCESS
    assert "test_3rdparty_transitive_dep.py ." in result.stdout

  @skip_unless_python27_and_python3_present
  def test_uses_correct_python_version(self) -> None:
    self.create_python_test_target([self.py3_only_source], interpreter_constraints='CPython==2.7.*')
    py2_result = self.run_pytest()
    assert py2_result.status == Status.FAILURE
    assert "SyntaxError: invalid syntax" in py2_result.stdout
    Path(self.build_root, self.source_root, "BUILD").unlink()  # Cleanup in order to recreate the target
    self.create_python_test_target([self.py3_only_source], interpreter_constraints='CPython>=3.6')
    py3_result = self.run_pytest()
    assert py3_result.status == Status.SUCCESS
    assert "test_py3.py ." in py3_result.stdout

  def test_respects_passthrough_args(self) -> None:
    source = FileContent(
      path="test_config.py",
      content=dedent(
        """\
        def test_run_me():
          pass
        
        def test_ignore_me():
          pass
        """
      ).encode(),
    )
    self.create_python_test_target([source])
    result = self.run_pytest(passthrough_args="-k test_run_me")
    assert result.status == Status.SUCCESS
    assert "test_config.py ." in result.stdout
    assert "collected 2 items / 1 deselected / 1 selected" in result.stdout
