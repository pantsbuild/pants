# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pathlib import PurePath
from textwrap import dedent
from typing import List, Optional

from pants.backend.python.dependency_inference import rules as dependency_inference_rules
from pants.backend.python.rules import inject_ancestor_files
from pants.backend.python.target_types import PythonLibrary
from pants.backend.python.typecheck.mypy.rules import MyPyFieldSet, MyPyRequest
from pants.backend.python.typecheck.mypy.rules import rules as mypy_rules
from pants.base.specs import SingleAddress
from pants.core.goals.typecheck import TypecheckResults
from pants.engine.addresses import Address
from pants.engine.fs import FileContent
from pants.engine.rules import RootRule
from pants.engine.selectors import Params
from pants.engine.target import TargetWithOrigin, WrappedTarget
from pants.testutil.external_tool_test_base import ExternalToolTestBase
from pants.testutil.option.util import create_options_bootstrapper


class MyPyIntegrationTest(ExternalToolTestBase):

    package = "src/python/project"
    good_source = FileContent(
        f"{package}/good.py",
        dedent(
            """\
            def add(x: int, y: int) -> int:
                return x + y

            result = add(3, 3)
            """
        ).encode(),
    )
    bad_source = FileContent(
        f"{package}/bad.py",
        dedent(
            """\
            def add(x: int, y: int) -> int:
                return x + y

            result = add(2.0, 3.0)
            """
        ).encode(),
    )
    needs_config_source = FileContent(
        f"{package}/needs_config.py",
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
        return (
            *super().rules(),
            *mypy_rules(),
            RootRule(MyPyRequest),
            # mypy needs __init__.py files in many cases: we pull in inference to avoid boilerplate.
            *dependency_inference_rules.rules(),
            *inject_ancestor_files.rules(),
        )

    @classmethod
    def target_types(cls):
        return [PythonLibrary]

    def make_target_with_origin(
        self,
        source_files: List[FileContent],
        *,
        package: Optional[str] = None,
        name: str = "target",
    ) -> TargetWithOrigin:
        if not package:
            package = self.package
        for source_file in source_files:
            self.create_file(source_file.path, source_file.content.decode())
        source_globs = [PurePath(source_file.path).name for source_file in source_files]
        self.add_to_build_file(
            f"{package}",
            dedent(
                f"""\
                python_library(
                    name={repr(name)},
                    sources={source_globs},
                )
                """
            ),
        )
        target = self.request_single_product(WrappedTarget, Address(package, name)).target
        origin = SingleAddress(directory=package, name=name)
        return TargetWithOrigin(target, origin)

    def run_mypy(
        self,
        targets: List[TargetWithOrigin],
        *,
        config: Optional[str] = None,
        passthrough_args: Optional[str] = None,
        skip: bool = False,
        additional_args: Optional[List[str]] = None,
    ) -> TypecheckResults:
        args = [
            "--backend-packages=pants.backend.python",
            "--backend-packages=pants.backend.python.typecheck.mypy",
            "--source-root-patterns=['src/python', 'tests/python']",
            "--python-infer-imports",
        ]
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
            TypecheckResults,
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
        assert f"{self.package}/bad.py:4" in result[0].stdout

    def test_mixed_sources(self) -> None:
        target = self.make_target_with_origin([self.good_source, self.bad_source])
        result = self.run_mypy([target])
        assert len(result) == 1
        assert result[0].exit_code == 1
        assert f"{self.package}/good.py" not in result[0].stdout
        assert f"{self.package}/bad.py:4" in result[0].stdout
        assert "checked 2 source files" in result[0].stdout

    def test_multiple_targets(self) -> None:
        targets = [
            self.make_target_with_origin([self.good_source], name="t1"),
            self.make_target_with_origin([self.bad_source], name="t2"),
        ]
        result = self.run_mypy(targets)
        assert len(result) == 1
        assert result[0].exit_code == 1
        assert f"{self.package}/good.py" not in result[0].stdout
        assert f"{self.package}/bad.py:4" in result[0].stdout
        assert "checked 2 source files" in result[0].stdout

    def test_respects_config_file(self) -> None:
        target = self.make_target_with_origin([self.needs_config_source])
        result = self.run_mypy([target], config="[mypy]\ndisallow_any_expr = True\n")
        assert len(result) == 1
        assert result[0].exit_code == 1
        assert f"{self.package}/needs_config.py:4" in result[0].stdout

    def test_respects_passthrough_args(self) -> None:
        target = self.make_target_with_origin([self.needs_config_source])
        result = self.run_mypy([target], passthrough_args="--disallow-any-expr")
        assert len(result) == 1
        assert result[0].exit_code == 1
        assert f"{self.package}/needs_config.py:4" in result[0].stdout

    def test_skip(self) -> None:
        target = self.make_target_with_origin([self.bad_source])
        result = self.run_mypy([target], skip=True)
        assert not result

    def test_transitive_dependencies(self) -> None:
        self.create_file(f"{self.package}/util/__init__.py")
        self.create_file(
            f"{self.package}/util/lib.py",
            dedent(
                """\
                def capitalize(v: str) -> str:
                    return v.capitalize()
                """
            ),
        )
        self.add_to_build_file(f"{self.package}/util", "python_library()")

        self.create_file(f"{self.package}/math/__init__.py")
        self.create_file(
            f"{self.package}/math/add.py",
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
            f"{self.package}/math", "python_library()",
        )

        sources_content = [
            FileContent(
                f"{self.package}/app.py",
                dedent(
                    """\
                        from project.math.add import add

                        print(add(2, 4))
                        """
                ).encode(),
            ),
            FileContent(f"{self.package}/__init__.py", b""),
        ]
        target = self.make_target_with_origin(sources_content)
        result = self.run_mypy([target])
        assert len(result) == 1
        assert result[0].exit_code == 1
        assert f"{self.package}/math/add.py:5" in result[0].stdout
