# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pathlib import PurePath
from textwrap import dedent
from typing import List, Optional

from pants.backend.python.lint.mypy.rules import MyPyFieldSet, MyPyRequest
from pants.backend.python.lint.mypy.rules import rules as mypy_rules
from pants.backend.python.target_types import PythonLibrary
from pants.base.specs import SingleAddress
from pants.core.goals.lint import LintResults
from pants.engine.addresses import Address
from pants.engine.fs import FileContent
from pants.engine.rules import RootRule
from pants.engine.selectors import Params
from pants.engine.target import TargetWithOrigin, WrappedTarget
from pants.testutil.external_tool_test_base import ExternalToolTestBase
from pants.testutil.option.util import create_options_bootstrapper


class MyPyIntegrationTest(ExternalToolTestBase):

    source_root = "src/python"
    good_source = FileContent(
        f"{source_root}/project/good.py",
        dedent(
            """\
            def add(x: int, y: int) -> int:
                return x + y

            result = add(3, 3)
            """
        ).encode(),
    )
    bad_source = FileContent(
        f"{source_root}/project/bad.py",
        dedent(
            """\
            def add(x: int, y: int) -> int:
                return x + y

            result = add(2.0, 3.0)
            """
        ).encode(),
    )
    needs_config_source = FileContent(
        f"{source_root}/project/needs_config.py",
        dedent(
            """\
            from typing import Any, cast

            # This will fail if `--disallow-any-expr` is configured.
            x = cast(Any, "hello")
            """
        ).encode(),
    )

    @classmethod
    def rules(cls):
        return (*super().rules(), *mypy_rules(), RootRule(MyPyRequest))

    @classmethod
    def target_types(cls):
        return [PythonLibrary]

    def make_target_with_origin(
        self,
        source_files: List[FileContent],
        *,
        name: str = "target",
        dependencies: Optional[List[Address]] = None,
    ) -> TargetWithOrigin:
        for source_file in source_files:
            self.create_file(source_file.path, source_file.content.decode())
        source_globs = [PurePath(source_file.path).name for source_file in source_files]
        self.add_to_build_file(
            f"{self.source_root}/project",
            dedent(
                f"""\
                python_library(
                    name={repr(name)},
                    sources={source_globs},
                    dependencies={[str(dep) for dep in dependencies or ()]},
                )
                """
            ),
        )
        target = self.request_single_product(
            WrappedTarget, Address(f"{self.source_root}/project", name)
        ).target
        origin = SingleAddress(directory=f"{self.source_root}/project", name=name)
        return TargetWithOrigin(target, origin)

    def run_mypy(
        self,
        targets: List[TargetWithOrigin],
        *,
        config: Optional[str] = None,
        passthrough_args: Optional[str] = None,
        skip: bool = False,
        additional_args: Optional[List[str]] = None,
    ) -> LintResults:
        args = ["--backend-packages2=pants.backend.python.lint.mypy"]
        if config:
            self.create_file(relpath="mypy.ini", contents=config)
            args.append("--mypy-config=mypy.ini")
        if passthrough_args:
            args.append(f"--mypy-args='{passthrough_args}'")
        if skip:
            args.append("--mypy-skip")
        if additional_args:
            args.extend(additional_args)
        return self.request_single_product(
            LintResults,
            Params(
                MyPyRequest(MyPyFieldSet.create(tgt) for tgt in targets),
                create_options_bootstrapper(args=args),
            ),
        )

    def test_passing_source(self) -> None:
        target = self.make_target_with_origin([self.good_source])
        result = self.run_mypy([target])
        assert len(result) == 1
        assert result[0].exit_code == 0
        assert "Success: no issues found" in result[0].stdout.strip()

    def test_failing_source(self) -> None:
        target = self.make_target_with_origin([self.bad_source])
        result = self.run_mypy([target])
        assert len(result) == 1
        assert result[0].exit_code == 1
        assert f"{self.source_root}/project/bad.py:4" in result[0].stdout

    def test_mixed_sources(self) -> None:
        target = self.make_target_with_origin([self.good_source, self.bad_source])
        result = self.run_mypy([target])
        assert len(result) == 1
        assert result[0].exit_code == 1
        assert f"{self.source_root}/project/good.py" not in result[0].stdout
        assert f"{self.source_root}/project/bad.py:4" in result[0].stdout
        assert "checked 3 source files" in result[0].stdout

    def test_multiple_targets(self) -> None:
        targets = [
            self.make_target_with_origin([self.good_source], name="t1"),
            self.make_target_with_origin([self.bad_source], name="t2"),
        ]
        result = self.run_mypy(targets)
        assert len(result) == 1
        assert result[0].exit_code == 1
        assert f"{self.source_root}/project/good.py" not in result[0].stdout
        assert f"{self.source_root}/project/bad.py:4" in result[0].stdout
        assert "checked 3 source files" in result[0].stdout

    def test_respects_config_file(self) -> None:
        target = self.make_target_with_origin([self.needs_config_source])
        result = self.run_mypy([target], config="[mypy]\ndisallow_any_expr = True\n")
        assert len(result) == 1
        assert result[0].exit_code == 1
        assert f"{self.source_root}/project/needs_config.py:4" in result[0].stdout

    def test_respects_passthrough_args(self) -> None:
        target = self.make_target_with_origin([self.needs_config_source])
        result = self.run_mypy([target], passthrough_args="--disallow-any-expr")
        assert len(result) == 1
        assert result[0].exit_code == 1
        assert f"{self.source_root}/project/needs_config.py:4" in result[0].stdout

    def test_skip(self) -> None:
        target = self.make_target_with_origin([self.bad_source])
        result = self.run_mypy([target], skip=True)
        assert not result

    def test_transitive_dependencies(self) -> None:
        self.create_file(
            f"{self.source_root}/project/util/lib.py",
            dedent(
                """\
                def capitalize(v: str) -> str:
                    return v.capitalize()
                """
            ),
        )
        self.add_to_build_file(f"{self.source_root}/project/util", "python_library()")
        self.create_file(
            f"{self.source_root}/project/math/add.py",
            dedent(
                """\
                from project.util.lib import capitalize

                def add(x: int, y: int) -> str:
                    sum = x + y
                    return capitalize(sum)  # This is the wrong type.
                """
            ),
        )
        self.add_to_build_file(
            f"{self.source_root}/project/math",
            f"python_library(dependencies=['{self.source_root}/project/util'])",
        )
        source_content = FileContent(
            f"{self.source_root}/project/app.py",
            dedent(
                """\
                from project.math.add import add

                print(add(2, 4))
                """
            ).encode(),
        )
        target = self.make_target_with_origin(
            [source_content], dependencies=[Address.parse(f"{self.source_root}/project/math")]
        )
        result = self.run_mypy([target])
        assert len(result) == 1
        assert result[0].exit_code == 1
        assert f"{self.source_root}/project/math/add.py:5" in result[0].stdout
