# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
import re
from pathlib import Path, PurePath
from textwrap import dedent
from typing import List, Optional

from pants.backend.python.dependency_inference import rules as dependency_inference_rules
from pants.backend.python.rules import pex, pex_from_targets, pytest_runner, python_sources
from pants.backend.python.rules.coverage import create_coverage_config
from pants.backend.python.rules.pytest_runner import PythonTestFieldSet
from pants.backend.python.target_types import PythonLibrary, PythonRequirementLibrary, PythonTests
from pants.build_graph.build_file_aliases import BuildFileAliases
from pants.core.goals.test import TestDebugRequest, TestResult
from pants.core.util_rules import source_files, stripped_source_files
from pants.engine.addresses import Address
from pants.engine.fs import DigestContents, FileContent
from pants.engine.process import InteractiveRunner
from pants.engine.rules import RootRule
from pants.python.python_requirement import PythonRequirement
from pants.testutil.engine.util import Params
from pants.testutil.external_tool_test_base import ExternalToolTestBase
from pants.testutil.interpreter_selection_utils import skip_unless_python27_and_python3_present
from pants.testutil.option.util import create_options_bootstrapper


class PytestRunnerIntegrationTest(ExternalToolTestBase):

    source_root = "tests/python"
    package = os.path.join(source_root, "pants_test")
    good_source = FileContent(path="test_good.py", content=b"def test():\n  pass\n")
    bad_source = FileContent(path="test_bad.py", content=b"def test():\n  assert False\n")
    py3_only_source = FileContent(path="test_py3.py", content=b"def test() -> None:\n  pass\n")
    library_source = FileContent(path="library.py", content=b"def add_two(x):\n  return x + 2\n")
    conftest_source = FileContent(
        path="conftest.py",
        content=b"def pytest_runtest_setup(item):\n" b"  print('In conftest!')\n",
    )

    def write_file(self, file_content: FileContent) -> None:
        self.create_file(
            relpath=PurePath(self.package, file_content.path).as_posix(),
            contents=file_content.content.decode(),
        )

    def create_python_library(
        self,
        source_files: List[FileContent],
        *,
        name: str = "library",
        dependencies: Optional[List[str]] = None,
    ) -> None:
        for source_file in source_files:
            self.write_file(source_file)
        source_globs = [PurePath(source_file.path).name for source_file in source_files] + [
            "__init__.py"
        ]
        self.add_to_build_file(
            self.package,
            dedent(
                f"""\
                python_library(
                    name={repr(name)},
                    sources={source_globs},
                    dependencies={[*(dependencies or ())]},
                )
                """
            ),
        )
        self.create_file(os.path.join(self.package, "__init__.py"))

    def create_python_test_target(
        self,
        source_files: List[FileContent],
        *,
        dependencies: Optional[List[str]] = None,
        interpreter_constraints: Optional[str] = None,
    ) -> None:
        self.add_to_build_file(
            relpath=self.package,
            target=dedent(
                f"""\
                python_tests(
                  name='target',
                  dependencies={dependencies or []},
                  compatibility={[interpreter_constraints] if interpreter_constraints else []},
                )
                """
            ),
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
        return BuildFileAliases(objects={"python_requirement": PythonRequirement})

    @classmethod
    def target_types(cls):
        return [PythonLibrary, PythonTests, PythonRequirementLibrary]

    @classmethod
    def rules(cls):
        return (
            *super().rules(),
            create_coverage_config,
            *pytest_runner.rules(),
            *python_sources.rules(),
            *pex.rules(),
            *pex_from_targets.rules(),
            *source_files.rules(),
            *stripped_source_files.rules(),
            RootRule(PythonTestFieldSet),
            # For conftest detection.
            *dependency_inference_rules.rules(),
        )

    def run_pytest(
        self,
        *,
        address: Optional[Address] = None,
        passthrough_args: Optional[str] = None,
        junit_xml_dir: Optional[str] = None,
        use_coverage: bool = False,
        execution_slot_var: Optional[str] = None,
    ) -> TestResult:
        args = [
            "--backend-packages=pants.backend.python",
            f"--source-root-patterns={self.source_root}",
            # pin to lower versions so that we can run Python 2 tests
            "--pytest-version=pytest>=4.6.6,<4.7",
            "--pytest-pytest-plugins=['zipp==1.0.0', 'pytest-cov>=2.8.1,<2.9']",
        ]
        if passthrough_args:
            args.append(f"--pytest-args='{passthrough_args}'")
        if junit_xml_dir:
            args.append(f"--pytest-junit-xml-dir={junit_xml_dir}")
        if use_coverage:
            args.append("--test-use-coverage")
        if execution_slot_var:
            args.append(f"--pytest-execution-slot-var={execution_slot_var}")
        if not address:
            address = Address(self.package, target_name="target")
        params = Params(
            PythonTestFieldSet.create(PythonTests({}, address=address)),
            create_options_bootstrapper(args=args),
        )
        test_result = self.request_single_product(TestResult, params)
        debug_request = self.request_single_product(TestDebugRequest, params)
        if debug_request.process is not None:
            debug_result = InteractiveRunner(self.scheduler).run(debug_request.process)
            assert test_result.exit_code == debug_result.exit_code
        return test_result

    def test_single_passing_test(self) -> None:
        self.create_python_test_target([self.good_source])
        result = self.run_pytest()
        assert result.exit_code == 0
        assert f"{self.package}/test_good.py ." in result.stdout

    def test_single_failing_test(self) -> None:
        self.create_python_test_target([self.bad_source])
        result = self.run_pytest()
        assert result.exit_code == 1
        assert f"{self.package}/test_bad.py F" in result.stdout

    def test_mixed_sources(self) -> None:
        self.create_python_test_target([self.good_source, self.bad_source])
        result = self.run_pytest()
        assert result.exit_code == 1
        assert f"{self.package}/test_good.py ." in result.stdout
        assert f"{self.package}/test_bad.py F" in result.stdout

    def test_absolute_import(self) -> None:
        self.create_python_library([self.library_source])
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
        assert result.exit_code == 0
        assert f"{self.package}/test_absolute_import.py ." in result.stdout

    def test_relative_import(self) -> None:
        self.create_python_library([self.library_source])
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
        assert result.exit_code == 0
        assert f"{self.package}/test_relative_import.py ." in result.stdout

    def test_transitive_dep(self) -> None:
        self.create_python_library([self.library_source])
        transitive_dep_fc = FileContent(
            path="transitive_dep.py",
            content=dedent(
                """\
                from pants_test.library import add_two

                def add_four(x):
                  return add_two(x) + 2
                """
            ).encode(),
        )
        self.create_python_library(
            [transitive_dep_fc], name="transitive_dep", dependencies=[":library"]
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
        assert result.exit_code == 0
        assert f"{self.package}/test_transitive_dep.py ." in result.stdout

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
        assert result.exit_code == 0
        assert f"{self.package}/test_3rdparty_dep.py ." in result.stdout

    def test_thirdparty_transitive_dep(self) -> None:
        self.setup_thirdparty_dep()
        library_fc = FileContent(
            path="library.py",
            content=dedent(
                """\
                import string
                from ordered_set import OrderedSet

                alphabet = OrderedSet(string.ascii_lowercase)
                """
            ).encode(),
        )
        self.create_python_library(
            [library_fc], dependencies=["3rdparty/python:ordered-set"],
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
        assert result.exit_code == 0
        assert f"{self.package}/test_3rdparty_transitive_dep.py ." in result.stdout

    @skip_unless_python27_and_python3_present
    def test_uses_correct_python_version(self) -> None:
        self.create_python_test_target(
            [self.py3_only_source], interpreter_constraints="CPython==2.7.*"
        )
        py2_result = self.run_pytest()
        assert py2_result.exit_code == 2
        assert "SyntaxError: invalid syntax" in py2_result.stdout
        Path(
            self.build_root, self.package, "BUILD"
        ).unlink()  # Cleanup in order to recreate the target
        self.create_python_test_target(
            [self.py3_only_source], interpreter_constraints="CPython>=3.6"
        )
        py3_result = self.run_pytest()
        assert py3_result.exit_code == 0
        assert f"{self.package}/test_py3.py ." in py3_result.stdout

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
        assert result.exit_code == 0
        assert f"{self.package}/test_config.py ." in result.stdout
        assert "collected 2 items / 1 deselected / 1 selected" in result.stdout

    def test_junit(self) -> None:
        self.create_python_test_target([self.good_source])
        result = self.run_pytest(junit_xml_dir="dist/test-results")
        assert result.exit_code == 0
        assert f"{self.package}/test_good.py ." in result.stdout
        assert result.xml_results is not None
        digest_contents = self.request_single_product(DigestContents, result.xml_results)
        assert len(digest_contents) == 1
        file = digest_contents[0]
        assert file.path.startswith("dist/test-results")
        assert b"pants_test.test_good" in file.content

    def test_coverage(self) -> None:
        self.create_python_test_target([self.good_source])
        result = self.run_pytest(use_coverage=True)
        assert result.exit_code == 0
        assert f"{self.package}/test_good.py ." in result.stdout
        assert result.coverage_data is not None

    def test_conftest_handling(self) -> None:
        """Tests that we a) inject a dependency on conftest.py and b) skip running directly on
        conftest.py."""
        self.create_python_test_target([self.good_source])
        self.create_file(
            PurePath(self.source_root, self.conftest_source.path).as_posix(),
            self.conftest_source.content.decode(),
        )
        self.add_to_build_file(self.source_root, "python_tests()")

        result = self.run_pytest(passthrough_args="-s")
        assert result.exit_code == 0
        assert f"{self.package}/test_good.py In conftest!\n." in result.stdout

        result = self.run_pytest(
            address=Address(self.source_root, relative_file_path="conftest.py")
        )
        assert result.exit_code is None

    def test_execution_slot_variable(self) -> None:
        source = FileContent(
            path="test_concurrency_slot.py",
            content=dedent(
                """\
                import os

                def test_fail_printing_slot_env_var():
                    slot = os.getenv("SLOT")
                    print(f"Value of slot is {slot}")
                    # Deliberately fail the test so the SLOT output gets printed to stdout
                    assert 1 == 2
                """
            ).encode(),
        )
        self.create_python_test_target([source])
        result = self.run_pytest(execution_slot_var="SLOT")
        assert result.exit_code == 1
        assert re.search(r"Value of slot is \d+", result.stdout)
