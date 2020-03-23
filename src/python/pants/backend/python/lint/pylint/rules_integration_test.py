# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from functools import partialmethod
from textwrap import dedent
from typing import List, Optional

from pants.backend.python.lint.pylint.rules import PylintLinter
from pants.backend.python.lint.pylint.rules import rules as pylint_rules
from pants.backend.python.targets.python_library import PythonLibrary
from pants.base.specs import FilesystemLiteralSpec, OriginSpec, SingleAddress
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

    @classmethod
    def alias_groups(cls) -> BuildFileAliases:
        return BuildFileAliases(targets={"python_library": PythonLibrary})

    @classmethod
    def rules(cls):
        return (*super().rules(), *pylint_rules(), RootRule(PylintLinter))

    def write_file(self, file_content: FileContent) -> None:
        self.create_file(relpath=file_content.path, contents=file_content.content.decode())

    def make_target_with_origin(
        self,
        source_files: List[FileContent],
        *,
        interpreter_constraints: Optional[str] = None,
        origin: Optional[OriginSpec] = None,
        dependencies: Optional[List[Address]] = None,
    ) -> PythonTargetAdaptorWithOrigin:
        input_snapshot = self.request_single_product(Snapshot, InputFilesContent(source_files))
        adaptor_kwargs = dict(
            sources=EagerFilesetWithSpec(self.source_root, {"globs": []}, snapshot=input_snapshot),
            address=Address.parse(f"{self.source_root}:target"),
            dependencies=dependencies or [],
        )
        if interpreter_constraints:
            adaptor_kwargs["compatibility"] = interpreter_constraints
        if origin is None:
            origin = SingleAddress(directory=self.source_root, name="target")
        return PythonTargetAdaptorWithOrigin(PythonTargetAdaptor(**adaptor_kwargs), origin)

    def run_pylint(
        self,
        targets: List[PythonTargetAdaptorWithOrigin],
        *,
        config: Optional[str] = None,
        passthrough_args: Optional[str] = None,
        skip: bool = False,
    ) -> LintResult:
        args = ["--backend-packages2=pants.backend.python.lint.pylint"]
        if config:
            self.create_file(relpath="pylintrc", contents=config)
            args.append("--pylint-config=pylintrc")
        if passthrough_args:
            args.append(f"--pylint-args='{passthrough_args}'")
        if skip:
            args.append(f"--pylint-skip")
        return self.request_single_product(
            LintResult,
            Params(PylintLinter(tuple(targets)), create_options_bootstrapper(args=args)),
        )

    def test_passing_source(self) -> None:
        self.create_python_library()
        self.write_file(self.good_source)
        target = self.make_target_with_origin([self.good_source])
        result = self.run_pylint([target])
        assert result.exit_code == 0
        assert "Your code has been rated at 10.00/10" in result.stdout.strip()

    def test_failing_source(self) -> None:
        self.create_python_library()
        self.write_file(self.bad_source)
        target = self.make_target_with_origin([self.bad_source])
        result = self.run_pylint([target])
        assert result.exit_code == 16  # convention message issued
        assert "bad.py:2:0: C0103" in result.stdout

    def test_mixed_sources(self) -> None:
        self.create_python_library()
        self.write_file(self.good_source)
        self.write_file(self.bad_source)
        target = self.make_target_with_origin([self.good_source, self.bad_source])
        result = self.run_pylint([target])
        assert result.exit_code == 16  # convention message issued
        assert "good.py" not in result.stdout
        assert "bad.py:2:0: C0103" in result.stdout

    def test_multiple_targets(self) -> None:
        self.create_python_library()
        self.write_file(self.good_source)
        self.write_file(self.bad_source)
        targets = [
            self.make_target_with_origin([self.good_source]),
            self.make_target_with_origin([self.bad_source]),
        ]
        result = self.run_pylint(targets)
        assert result.exit_code == 16  # convention message issued
        assert "good.py" not in result.stdout
        assert "bad.py:2:0: C0103" in result.stdout

    def test_precise_file_args(self) -> None:
        self.create_python_library()
        self.write_file(self.good_source)
        self.write_file(self.bad_source)
        target = self.make_target_with_origin(
            [self.good_source, self.bad_source], origin=FilesystemLiteralSpec(self.good_source.path)
        )
        result = self.run_pylint([target])
        assert result.exit_code == 0
        assert "Your code has been rated at 10.00/10" in result.stdout.strip()

    def test_respects_config_file(self) -> None:
        self.create_python_library()
        self.write_file(self.bad_source)
        target = self.make_target_with_origin([self.bad_source])
        result = self.run_pylint([target], config="[pylint]\ndisable = C0103\n")
        assert result.exit_code == 0
        assert "Your code has been rated at 10.00/10" in result.stdout.strip()

    def test_respects_passthrough_args(self) -> None:
        self.create_python_library()
        self.write_file(self.bad_source)
        target = self.make_target_with_origin([self.bad_source])
        result = self.run_pylint([target], passthrough_args="--disable=C0103")
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
        target = self.make_target_with_origin(
            [source], dependencies=[Address.parse(f"{self.source_root}:dependency")]
        )
        result = self.run_pylint([target])
        assert result.exit_code == 0
        assert "Your code has been rated at 10.00/10" in result.stdout.strip()

    def test_skip(self) -> None:
        target = self.make_target_with_origin([self.bad_source])
        result = self.run_pylint([target], skip=True)
        assert result == LintResult.noop()
