# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
from functools import partialmethod
from pathlib import Path, PurePath
from textwrap import dedent
from typing import List, Optional

import pytest

from pants.backend.python.rules import (
    download_pex_bin,
    importable_python_sources,
    pex,
    pex_from_targets,
    pytest_runner,
)
from pants.backend.python.rules.coverage import create_coverage_config, prepare_coverage_plugin
from pants.backend.python.rules.pytest_runner import PythonTestFieldSet
from pants.backend.python.subsystems import python_native_code, subprocess_environment
from pants.backend.python.target_types import PythonLibrary, PythonRequirementLibrary, PythonTests
from pants.backend.python.targets.python_library import PythonLibrary as PythonLibraryV1
from pants.backend.python.targets.python_requirement_library import (
    PythonRequirementLibrary as PythonRequirementLibraryV1,
)
from pants.backend.python.targets.python_tests import PythonTests as PythonTestsV1
from pants.base.specs import FilesystemLiteralSpec, OriginSpec, SingleAddress
from pants.build_graph.build_file_aliases import BuildFileAliases
from pants.core.goals.test import (
    Status,
    TestDebugRequest,
    TestOptions,
    TestResult,
    get_filtered_environment,
)
from pants.core.util_rules import determine_source_files, pants_environment, strip_source_roots
from pants.core.util_rules.pants_environment import PantsEnvironment
from pants.engine.addresses import Address
from pants.engine.fs import FileContent, FilesContent
from pants.engine.interactive_process import InteractiveRunner
from pants.engine.rules import RootRule, SubsystemRule
from pants.engine.selectors import Params
from pants.engine.target import TargetWithOrigin
from pants.python.python_requirement import PythonRequirement
from pants.testutil.external_tool_test_base import ExternalToolTestBase
from pants.testutil.interpreter_selection_utils import skip_unless_python27_and_python3_present
from pants.testutil.option.util import create_options_bootstrapper


# TODO: Figure out what testing should look like with the Target API. Should we still call
#  self.add_to_build_file(), for example?
class PytestRunnerIntegrationTest(ExternalToolTestBase):

    source_root = "tests/python"
    package = os.path.join(source_root, "pants_test")
    good_source = FileContent(path="test_good.py", content=b"def test():\n  pass\n")
    bad_source = FileContent(path="test_bad.py", content=b"def test():\n  assert False\n")
    py3_only_source = FileContent(path="test_py3.py", content=b"def test() -> None:\n  pass\n")
    library_source = FileContent(path="library.py", content=b"def add_two(x):\n  return x + 2\n")

    create_python_library = partialmethod(
        ExternalToolTestBase.create_library, path=package, target_type="python_library",
    )

    def write_file(self, file_content: FileContent) -> None:
        self.create_file(
            relpath=PurePath(self.package, file_content.path).as_posix(),
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
        return BuildFileAliases(
            targets={
                "python_library": PythonLibraryV1,
                "python_tests": PythonTestsV1,
                "python_requirement_library": PythonRequirementLibraryV1,
            },
            objects={"python_requirement": PythonRequirement},
        )

    @classmethod
    def target_types(cls):
        return [PythonLibrary, PythonTests, PythonRequirementLibrary]

    @classmethod
    def rules(cls):
        return (
            *super().rules(),
            create_coverage_config,
            prepare_coverage_plugin,
            *pytest_runner.rules(),
            *download_pex_bin.rules(),
            *determine_source_files.rules(),
            *importable_python_sources.rules(),
            *pants_environment.rules(),
            *pex.rules(),
            *pex_from_targets.rules(),
            *python_native_code.rules(),
            *strip_source_roots.rules(),
            *subprocess_environment.rules(),
            get_filtered_environment,
            SubsystemRule(TestOptions),
            RootRule(PythonTestFieldSet),
        )

    def run_pytest(
        self,
        *,
        passthrough_args: Optional[str] = None,
        origin: Optional[OriginSpec] = None,
        junit_xml_dir: Optional[str] = None,
        use_coverage: bool = False,
        extra_env_vars: Optional[str] = None,
        pants_environment: PantsEnvironment = PantsEnvironment(),
    ) -> TestResult:
        args = [
            "--backend-packages2=pants.backend.python",
            f"--source-root-patterns={self.source_root}",
            # pin to lower versions so that we can run Python 2 tests
            "--pytest-version=pytest>=4.6.6,<4.7",
            "--pytest-pytest-plugins=['zipp==1.0.0']",
        ]
        if passthrough_args:
            args.append(f"--pytest-args='{passthrough_args}'")
        if extra_env_vars:
            args.append(f"--test-extra-env-vars={extra_env_vars}")
        if junit_xml_dir:
            args.append(f"--pytest-junit-xml-dir={junit_xml_dir}")
        if use_coverage:
            args.append("--test-use-coverage")
        options_bootstrapper = create_options_bootstrapper(args=args)
        address = Address(self.package, "target")
        if origin is None:
            origin = SingleAddress(directory=address.spec_path, name=address.target_name)
        tgt = PythonTests({}, address=address)
        params = Params(
            PythonTestFieldSet.create(TargetWithOrigin(tgt, origin)),
            pants_environment,
            options_bootstrapper,
        )
        test_result = self.request_single_product(TestResult, params)
        debug_request = self.request_single_product(TestDebugRequest, params)
        debug_result = InteractiveRunner(self.scheduler).run_process(debug_request.process)
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

    def test_precise_file_args(self) -> None:
        self.create_python_test_target([self.good_source, self.bad_source])
        file_arg = FilesystemLiteralSpec(PurePath(self.package, self.good_source.path).as_posix())
        result = self.run_pytest(origin=file_arg)
        assert result.status == Status.SUCCESS
        assert "test_good.py ." in result.stdout
        assert "test_bad.py F" not in result.stdout

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
        self.create_python_test_target(
            [self.py3_only_source], interpreter_constraints="CPython==2.7.*"
        )
        py2_result = self.run_pytest()
        assert py2_result.status == Status.FAILURE
        assert "SyntaxError: invalid syntax" in py2_result.stdout
        Path(
            self.build_root, self.package, "BUILD"
        ).unlink()  # Cleanup in order to recreate the target
        self.create_python_test_target(
            [self.py3_only_source], interpreter_constraints="CPython>=3.6"
        )
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

    def test_single_passing_test_with_junit(self) -> None:
        self.create_python_test_target([self.good_source])
        result = self.run_pytest(junit_xml_dir="dist/test-results")

        assert result.status == Status.SUCCESS
        assert "test_good.py ." in result.stdout
        assert result.xml_results is not None

        files: FilesContent = self.request_single_product(FilesContent, result.xml_results)
        assert len(files) == 1
        file = files[0]
        assert file.path.startswith("dist/test-results")
        assert b"pants_test.test_good" in file.content

    @pytest.mark.skip(reason="https://github.com/pantsbuild/pants/issues/10141")
    def test_single_passing_test_with_coverage(self) -> None:
        self.create_python_test_target([self.good_source])
        result = self.run_pytest(use_coverage=True)

        assert result.status == Status.SUCCESS
        assert "test_good.py ." in result.stdout
        assert result.coverage_data is not None

    def test_extra_env_vars(self) -> None:
        source = FileContent(
            path="test_extra_env_vars.py",
            content=dedent(
                """\
                import os
                def test_args():
                    assert os.getenv("SOME_VAR") == "some_value"
                    assert os.getenv("OTHER_VAR") == "other_value"
                """
            ).encode(),
        )
        self.create_python_test_target([source])
        mock_env = PantsEnvironment({"OTHER_VAR": "other_value"})
        extra_env_vars = '["SOME_VAR=some_value", "OTHER_VAR"]'
        result = self.run_pytest(extra_env_vars=extra_env_vars, pants_environment=mock_env)
        assert result.status == Status.SUCCESS
