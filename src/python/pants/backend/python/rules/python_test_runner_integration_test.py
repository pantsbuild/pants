# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from functools import partialmethod
from pathlib import Path, PurePath
from textwrap import dedent
from typing import List, Optional

from pants.backend.python.rules import (
    download_pex_bin,
    pex,
    pex_from_target_closure,
    prepare_chrooted_python_sources,
    python_test_runner,
)
from pants.backend.python.subsystems import python_native_code, subprocess_environment
from pants.backend.python.targets.python_library import PythonLibrary
from pants.backend.python.targets.python_requirement_library import PythonRequirementLibrary
from pants.backend.python.targets.python_tests import PythonTests
from pants.base.specs import FilesystemLiteralSpec, OriginSpec, SingleAddress
from pants.build_graph.build_file_aliases import BuildFileAliases
from pants.engine.fs import FileContent
from pants.engine.interactive_runner import InteractiveRunner
from pants.engine.legacy.structs import PythonTestsAdaptor, PythonTestsAdaptorWithOrigin
from pants.engine.rules import RootRule, subsystem_rule
from pants.engine.selectors import Params
from pants.python.python_requirement import PythonRequirement
from pants.rules.core import determine_specified_source_files, strip_source_roots
from pants.rules.core.test import Status, TestDebugRequest, TestOptions, TestResult
from pants.testutil.interpreter_selection_utils import skip_unless_python27_and_python3_present
from pants.testutil.option.util import create_options_bootstrapper
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
            relpath=PurePath(self.source_root, file_content.path).as_posix(),
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
                "python_library": PythonLibrary,
                "python_tests": PythonTests,
                "python_requirement_library": PythonRequirementLibrary,
            },
            objects={"python_requirement": PythonRequirement,},
        )

    @classmethod
    def rules(cls):
        return (
            *super().rules(),
            *python_test_runner.rules(),
            *download_pex_bin.rules(),
            *determine_specified_source_files.rules(),
            *pex.rules(),
            *pex_from_target_closure.rules(),
            *prepare_chrooted_python_sources.rules(),
            *python_native_code.rules(),
            *strip_source_roots.rules(),
            *subprocess_environment.rules(),
            subsystem_rule(TestOptions),
            RootRule(PythonTestsAdaptorWithOrigin),
        )

    def run_pytest(
        self, *, passthrough_args: Optional[str] = None, origin: Optional[OriginSpec] = None,
    ) -> TestResult:
        args = [
            "--backend-packages2=pants.backend.python",
            # pin to lower versions so that we can run Python 2 tests
            "--pytest-version=pytest>=4.6.6,<4.7",
            "--pytest-pytest-plugins=['zipp==1.0.0']",
        ]
        if passthrough_args:
            args.append(f"--pytest-args='{passthrough_args}'")
        options_bootstrapper = create_options_bootstrapper(args=args)
        if origin is None:
            origin = SingleAddress(directory=self.source_root, name="target")
        # TODO: We must use the V1 target's `_sources_field.sources` field to set the TargetAdaptor's
        # sources attribute. The adaptor will not auto-populate this field. However, it will
        # auto-populate things like `dependencies` and this was not necessary before using
        # PythonTestsAdaptorWithOrigin. Why is this necessary in test code?
        v1_target = self.target(f"{self.source_root}:target")
        adaptor = PythonTestsAdaptor(
            address=v1_target.address.to_address(), sources=v1_target._sources_field.sources,
        )
        params = Params(PythonTestsAdaptorWithOrigin(adaptor, origin), options_bootstrapper)
        test_result = self.request_single_product(TestResult, params)
        debug_request = self.request_single_product(TestDebugRequest, params)
        debug_result = InteractiveRunner(self.scheduler).run_local_interactive_process(
            debug_request.ipr
        )
        if test_result.status == Status.SUCCESS:
            assert debug_result.process_exit_code == 0
        else:
            assert debug_result.process_exit_code != 0
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
        file_arg = FilesystemLiteralSpec(
            PurePath(self.source_root, self.good_source.path).as_posix()
        )
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
            self.build_root, self.source_root, "BUILD"
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
