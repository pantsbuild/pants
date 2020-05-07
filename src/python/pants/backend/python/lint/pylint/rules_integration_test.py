# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pathlib import PurePath
from textwrap import dedent
from typing import List, Optional

from pants.backend.python.lint.pylint.rules import PylintFieldSet, PylintFieldSets
from pants.backend.python.lint.pylint.rules import rules as pylint_rules
from pants.backend.python.target_types import PythonInterpreterCompatibility, PythonLibrary
from pants.backend.python.targets.python_library import PythonLibrary as PythonLibraryV1
from pants.base.specs import FilesystemLiteralSpec, OriginSpec, SingleAddress
from pants.build_graph.build_file_aliases import BuildFileAliases
from pants.core.goals.lint import LintResult
from pants.engine.addresses import Address
from pants.engine.fs import FileContent
from pants.engine.legacy.graph import HydratedTargets
from pants.engine.rules import RootRule
from pants.engine.selectors import Params
from pants.engine.target import Dependencies, Sources, TargetWithOrigin
from pants.testutil.external_tool_test_base import ExternalToolTestBase
from pants.testutil.option.util import create_options_bootstrapper


class PylintIntegrationTest(ExternalToolTestBase):
    # See http://pylint.pycqa.org/en/latest/user_guide/run.html#exit-codes for exit codes.
    source_root = "src/python"
    good_source = FileContent(
        path=f"{source_root}/good.py", content=b"'''docstring'''\nUPPERCASE_CONSTANT = ''\n",
    )
    bad_source = FileContent(
        path=f"{source_root}/bad.py", content=b"'''docstring'''\nlowercase_constant = ''\n",
    )

    @classmethod
    def alias_groups(cls) -> BuildFileAliases:
        return BuildFileAliases(targets={"python_library": PythonLibraryV1})

    @classmethod
    def target_types(cls):
        return [PythonLibrary]

    @classmethod
    def rules(cls):
        return (
            *super().rules(),
            *pylint_rules(),
            RootRule(PylintFieldSets),
            RootRule(HydratedTargets),
        )

    def make_target_with_origin(
        self,
        source_files: List[FileContent],
        *,
        name: str = "target",
        interpreter_constraints: Optional[str] = None,
        origin: Optional[OriginSpec] = None,
        dependencies: Optional[List[Address]] = None,
    ) -> TargetWithOrigin:
        for source_file in source_files:
            self.create_file(source_file.path, source_file.content.decode())
        source_globs = [PurePath(source_file.path).name for source_file in source_files]
        self.create_library(
            path=self.source_root, target_type=PythonLibrary.alias, name=name, sources=source_globs
        )
        # We must re-write the files because `create_library` will have over-written the content.
        for source_file in source_files:
            self.create_file(source_file.path, source_file.content.decode())
        target = PythonLibrary(
            {
                Sources.alias: source_globs,
                Dependencies.alias: dependencies,
                PythonInterpreterCompatibility.alias: interpreter_constraints,
            },
            address=Address(self.source_root, name),
        )
        if origin is None:
            origin = SingleAddress(directory=self.source_root, name=name)
        return TargetWithOrigin(target, origin)

    def run_pylint(
        self,
        targets: List[TargetWithOrigin],
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
            Params(
                PylintFieldSets(PylintFieldSet.create(tgt) for tgt in targets),
                create_options_bootstrapper(args=args),
            ),
        )

    def test_passing_source(self) -> None:
        target = self.make_target_with_origin([self.good_source])
        result = self.run_pylint([target])
        assert result.exit_code == 0
        assert "Your code has been rated at 10.00/10" in result.stdout.strip()

    def test_failing_source(self) -> None:
        target = self.make_target_with_origin([self.bad_source])
        result = self.run_pylint([target])
        assert result.exit_code == 16  # convention message issued
        assert "bad.py:2:0: C0103" in result.stdout

    def test_mixed_sources(self) -> None:
        target = self.make_target_with_origin([self.good_source, self.bad_source])
        result = self.run_pylint([target])
        assert result.exit_code == 16  # convention message issued
        assert "good.py" not in result.stdout
        assert "bad.py:2:0: C0103" in result.stdout

    def test_multiple_targets(self) -> None:
        targets = [
            self.make_target_with_origin([self.good_source], name="t1"),
            self.make_target_with_origin([self.bad_source], name="t2"),
        ]
        result = self.run_pylint(targets)
        assert result.exit_code == 16  # convention message issued
        assert "good.py" not in result.stdout
        assert "bad.py:2:0: C0103" in result.stdout

    def test_precise_file_args(self) -> None:
        target = self.make_target_with_origin(
            [self.good_source, self.bad_source], origin=FilesystemLiteralSpec(self.good_source.path)
        )
        result = self.run_pylint([target])
        assert result.exit_code == 0
        assert "Your code has been rated at 10.00/10" in result.stdout.strip()

    def test_respects_config_file(self) -> None:
        target = self.make_target_with_origin([self.bad_source])
        result = self.run_pylint([target], config="[pylint]\ndisable = C0103\n")
        assert result.exit_code == 0
        assert "Your code has been rated at 10.00/10" in result.stdout.strip()

    def test_respects_passthrough_args(self) -> None:
        target = self.make_target_with_origin([self.bad_source])
        result = self.run_pylint([target], passthrough_args="--disable=C0103")
        assert result.exit_code == 0
        assert "Your code has been rated at 10.00/10" in result.stdout.strip()

    def test_includes_direct_dependencies(self) -> None:
        self.make_target_with_origin(source_files=[], name="transitive_dependency")

        direct_dependency_content = dedent(
            """\
            # No docstring because Pylint doesn't lint dependencies

            from transitive_dep import doesnt_matter_if_variable_exists

            THIS_VARIABLE_EXISTS = ''
            """
        )
        self.make_target_with_origin(
            source_files=[
                FileContent(
                    f"{self.source_root}/direct_dependency.py", direct_dependency_content.encode()
                )
            ],
            name="direct_dependency",
            dependencies=[Address(self.source_root, "transitive_dependency")],
        )

        source_content = dedent(
            """\
            '''Code is not executed, but Pylint will check that variables exist and are used'''
            from direct_dependency import THIS_VARIABLE_EXISTS

            print(THIS_VARIABLE_EXISTS)
            """
        )
        target = self.make_target_with_origin(
            source_files=[FileContent(f"{self.source_root}/target.py", source_content.encode())],
            dependencies=[Address(self.source_root, "direct_dependency")],
        )

        result = self.run_pylint([target])
        assert result.exit_code == 0
        assert "Your code has been rated at 10.00/10" in result.stdout.strip()

    def test_skip(self) -> None:
        target = self.make_target_with_origin([self.bad_source])
        result = self.run_pylint([target], skip=True)
        assert result == LintResult.noop()
